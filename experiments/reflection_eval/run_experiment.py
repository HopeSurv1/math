# -*- coding: utf-8 -*-
"""
experiments/reflection_eval/run_experiment.py
功能簡介：反思機制開／關比較實驗的第 1 步——把 scenarios.json 的情境一題一題送進 /api/chat
          （跟網站走同一條流程：查課本、畫圖、反思機制都會跑），記下兩個版本：
            無反思 ＝ 反思機制檢查前的原稿
            有反思 ＝ 學生最後看到的回覆（檢查通過就跟原稿一樣；有問題就是改寫後的版本）
          所以不用把反思機制開一次、關一次各跑一遍：每題跑一次就同時拿到兩個版本，比的也是同一份原稿。
          時間：有反思 ＝ 整輪花的秒數；無反思 ＝ 整輪秒數扣掉反思機制花的秒數。
使用方式：
  py experiments/reflection_eval/run_experiment.py                  跑還沒跑過的題目（可以分好幾天跑）
  py experiments/reflection_eval/run_experiment.py --only A01 B02   只跑（或重跑）指定題目
  py experiments/reflection_eval/run_experiment.py --chat-model gemini-3.5-flash-lite
                                                                    老師回答也改用備援模型，不用主要模型一天 20 次的額度
輸出（都在 results/）：raw.jsonl（一行一題）、images/（這次實驗畫的圖）、
      experiment.db（實驗專用的資料庫，不會動到 data/conversations.db）
相依：專案根目錄的 .env 要有 GEMINI_API_KEY。
"""

import argparse
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="反思機制開／關比較實驗：跑情境、記下原稿和最後回覆")
    parser.add_argument("--only", nargs="+", metavar="題號", help="只跑這些題號（例如 A01 B02），跑過的也會重跑")
    parser.add_argument("--chat-model", help="老師回答改用這個模型，例如 gemini-3.5-flash-lite")
    parser.add_argument("--pause", type=float, default=5, help="每題之間休息幾秒（預設 5），免得撞到每分鐘上限")
    return parser.parse_args(argv)


if __name__ == "__main__":
    ARGS = parse_args()
    if ARGS.chat_model:
        # 要在 import src 之前設：config 在 import 時讀環境變數，.env 不會蓋掉已經設好的值
        os.environ["CHAT_MODEL"] = ARGS.chat_model

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from fastapi.testclient import TestClient  # noqa: E402

from common import RESULTS, load_raw, load_scenarios  # noqa: E402
from src.api import main  # noqa: E402
from src.config import config  # noqa: E402
from src.services import auth_store, conversation_store, learning_store  # noqa: E402

USERNAME, PASSWORD = "reflection-exp", "reflection-exp-1234"
GENERATED_DIR = ROOT / "src" / "frontend" / "generated"
_IMAGE_URL_RE = re.compile(r"/generated/([^)\s]+?\.png)")
_ERROR_PREFIX = "[系統錯誤]"
_STATUS_TEXT = {learning_store.REVIEW_OK: "檢查通過",
                learning_store.REVIEW_REVISED: "發現問題，已改寫",
                learning_store.REVIEW_FLAGGED: "發現問題，但改寫沒成功"}


class ScenarioFailed(Exception):
    """這題這次沒跑成（模型忙線、反思機制沒做成…）：不記錄，下次再跑。"""


def setup(results_dir=RESULTS):
    """換成實驗專用的資料庫並登入實驗帳號；反思機制強制打開，背景學習標記關掉（用不到，省額度）。"""
    (results_dir / "images").mkdir(parents=True, exist_ok=True)
    db_path = results_dir / "experiment.db"
    auth_store.DB_PATH = db_path
    conversation_store.DB_PATH = db_path
    config.REPLY_REVIEW = True
    main._record_learning = lambda *args, **kwargs: None
    client = TestClient(main.app)
    client.post("/api/register", json={"username": USERNAME, "password": PASSWORD})  # 已經註冊過會失敗，沒關係
    res = client.post("/api/login", json={"username": USERNAME, "password": PASSWORD})
    if res.status_code != 200:
        raise SystemExit(f"實驗帳號登入失敗：{res.text}")
    return client


def _move_images(text, results_dir):
    """這題畫的圖從 src/frontend/generated/ 搬到 results/images/，回覆裡的網址跟著改成 images/檔名。"""
    def move(match):
        name = match.group(1)
        source = GENERATED_DIR / name
        if source.exists():
            shutil.move(str(source), str(results_dir / "images" / name))
        return f"images/{name}"
    return _IMAGE_URL_RE.sub(move, text)


def run_scenario(client, scenario, results_dir=RESULTS):
    """跑一題：開新對話串、先寫入情境裡的先前對話，再送出學生這句話。回傳要存進 raw.jsonl 的紀錄。"""
    conversation_id = conversation_store.create_conversation(USERNAME)
    for role, text in scenario.get("history", []):
        conversation_store.append_message(conversation_id, role, text)

    start = time.perf_counter()
    res = client.post("/api/chat", json={"message": scenario["message"], "conversation_id": conversation_id})
    total_seconds = time.perf_counter() - start
    reply = res.json().get("reply", "") if res.status_code == 200 else ""
    if not reply or reply.startswith(_ERROR_PREFIX):
        raise ScenarioFailed(f"老師沒有回答成功：{reply or res.text}"[:300])

    with closing(sqlite3.connect(str(conversation_store.DB_PATH))) as conn:
        row = conn.execute("SELECT status, problems, draft, seconds FROM reply_reviews "
                           "WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
    if row is None or row[0] == learning_store.REVIEW_SKIPPED:
        raise ScenarioFailed("反思機制這次沒做成（忙線或逾時），沒辦法比較")
    status, problems, draft, review_seconds = row
    if status == learning_store.REVIEW_OK or not draft:
        draft = reply  # 檢查通過：學生看到的就是原稿

    return {
        "id": scenario["id"],
        "type": scenario["type"],
        "status": status,
        "problems": json.loads(problems or "[]"),  # 反思機制自己認為的問題，只供參考，不拿來計分
        "draft": _move_images(draft, results_dir),
        "final": _move_images(reply, results_dir),
        "total_seconds": round(total_seconds, 2),
        "review_seconds": round(review_seconds, 2),
        "chat_model": config.CHAT_MODEL,
        "review_model": config.REVIEW_MODEL,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }


def main_cli(args):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.getLogger("math_rag").setLevel(logging.WARNING)  # 後端每一步都會印紀錄，實驗時只留警告
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY.startswith("your_"):
        raise SystemExit("找不到 GEMINI_API_KEY：請先把 .env.example 複製成 .env，填入金鑰")

    scenarios = load_scenarios()
    done = load_raw()
    if args.only:
        unknown = set(args.only) - {s["id"] for s in scenarios}
        if unknown:
            raise SystemExit(f"scenarios.json 裡沒有這些題號：{'、'.join(sorted(unknown))}")
        todo = [s for s in scenarios if s["id"] in args.only]
    else:
        todo = [s for s in scenarios if s["id"] not in done]
    print(f"老師用的模型：{config.CHAT_MODEL}（備援：{config.FALLBACK_CHAT_MODEL}）；檢查用的模型：{config.REVIEW_MODEL}")
    print(f"已完成 {len(done)}/{len(scenarios)} 題，這次要跑 {len(todo)} 題。")
    used = {(r.get("chat_model"), r.get("review_model")) for r in done.values()}
    if used and used != {(config.CHAT_MODEL, config.REVIEW_MODEL)}:
        print("【警告】之前跑過的題目用的模型跟這次不一樣（老師／檢查）：" + "、".join(f"{c}／{r}" for c, r in sorted(used)))
        print(f"        這次是 {config.CHAT_MODEL}／{config.REVIEW_MODEL}。不同模型的結果混在一起不能比，"
              "請把 .env 改回一樣的設定，或刪掉 results 資料夾全部重跑。")
        if input("真的要繼續嗎？（輸入 y 繼續）").strip().lower() != "y":
            return
    if not todo:
        print("全部都跑完了，下一步：py experiments/reflection_eval/make_sheet.py")
        return

    client = setup()
    failures_in_a_row = 0
    with open(RESULTS / "raw.jsonl", "a", encoding="utf-8") as out:
        for i, scenario in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {scenario['id']}（{scenario['type']}）{scenario['message'][:30]}", flush=True)
            try:
                record = run_scenario(client, scenario)
            except ScenarioFailed as e:
                failures_in_a_row += 1
                print(f"    失敗，下次再跑：{e}")
                if failures_in_a_row >= 3:
                    print("連續 3 題失敗，可能是額度用完或模型大塞車。先停下來，晚點再執行一次（跑過的會自動跳過）。")
                    break
            else:
                failures_in_a_row = 0
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                print(f"    {_STATUS_TEXT.get(record['status'], record['status'])}，"
                      f"共 {record['total_seconds']} 秒（反思 {record['review_seconds']} 秒）")
            if i < len(todo):
                time.sleep(args.pause)

    done = load_raw()
    print(f"\n目前完成 {len(done)}/{len(scenarios)} 題。")
    if len(done) == len(scenarios):
        print("全部跑完了，下一步：py experiments/reflection_eval/make_sheet.py")
    else:
        print("還有題目沒跑完，再執行一次這支程式就會接著跑。")


if __name__ == "__main__":
    main_cli(ARGS)
