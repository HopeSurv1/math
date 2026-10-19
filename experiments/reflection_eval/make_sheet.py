# -*- coding: utf-8 -*-
"""
experiments/reflection_eval/make_sheet.py
功能簡介：反思機制實驗的第 2 步——從 results/raw.jsonl 產生人工判讀表。
          預設：回覆A 固定是原稿（無反思）、回覆B 固定是最後回覆（有反思），判讀的人知道哪個是哪個（不是盲測）。
          加 --blind：每題隨機排成 A／B，判讀的人看不出哪個經過反思（盲測，信度較高）。
          兩個版本一模一樣（檢查通過、沒改寫）時，回覆B 寫「與回覆A相同」，只要判讀 A。
          哪個是哪個記在 answer_key.json（score.py 算分用；盲測時判讀的人不要打開）。
使用方式：py experiments/reflection_eval/make_sheet.py [--blind]   （已經有判讀表時不會覆蓋，要重做請加 --force）
輸出：results/judge.html（判讀網頁：一題一頁、兩個回覆並排、勾選後匯出 CSV；用瀏覽器打開）、
      results/judge_sheet.csv（同樣內容的 Excel 版，長文字很難讀）、results/answer_key.json
      網頁的版面在 judge_template.html。
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NO_REVIEW, RESULTS, WITH_REVIEW, load_raw, load_scenarios  # noqa: E402

SEED = 20261001  # 固定亂數種子：同一份結果每次排出來的 A／B 都一樣
SAME = "（與回覆A相同，只要判讀A）"
KINDS = ("直接給答案", "數學錯誤", "與課本不一致")
COLUMNS = (["題號", "類型", "判讀提示", "先前對話", "學生這句", "回覆A"] + [f"A{k}" for k in KINDS]
           + ["回覆B"] + [f"B{k}" for k in KINDS] + ["備註"])
_ROLE = {"user": "學生", "model": "老師"}


def build_sheet(scenarios, raw, seed=SEED, blind=False):
    """回傳 (判讀表的每一列, 答案卷)。答案卷：{題號: "same"} 或 {題號: {"A": 版本, "B": 版本}}。
    blind=False（預設）：回覆A 固定是原稿（無反思），回覆B 固定是最後回覆（有反思；一樣就寫「與回覆A相同」）。
    blind=True：每題隨機排成 A／B，判讀的人看不出哪個經過反思。"""
    rng = random.Random(seed)
    rows, key = [], {}
    for scenario in scenarios:
        record = raw.get(scenario["id"])
        if record is None:
            continue
        draft, final = record["draft"].strip(), record["final"].strip()
        if draft == final:
            reply_a, reply_b = draft, SAME
            key[scenario["id"]] = "same"
        elif not blind or rng.random() < 0.5:
            reply_a, reply_b = draft, final
            key[scenario["id"]] = {"A": NO_REVIEW, "B": WITH_REVIEW}
        else:
            reply_a, reply_b = final, draft
            key[scenario["id"]] = {"A": WITH_REVIEW, "B": NO_REVIEW}
        history = "\n".join(f"{_ROLE.get(role, role)}：{text}" for role, text in scenario.get("history", []))
        blank = [""] * len(KINDS)
        rows.append([scenario["id"], scenario["type"], scenario["hint"], history, scenario["message"], reply_a]
                    + blank + [reply_b] + blank + [""])
    return rows, key


def build_page(rows):
    """判讀網頁（judge.html）：一題一頁、兩個回覆並排、用勾選框，勾完匯出成 score.py 讀得懂的 CSV。
    網頁裡只有題目和兩個回覆，沒有答案卷，判讀的人看原始碼也不知道哪個是反思過的。"""
    data = {"columns": COLUMNS, "kinds": list(KINDS), "same": SAME, "rows": rows,
            "fingerprint": hashlib.sha1(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # 不讓回覆裡的 </script> 提早結束網頁的程式
    template = (Path(__file__).resolve().parent / "judge_template.html").read_text(encoding="utf-8")
    return template.replace("__DATA__", payload)


def write_sheet(rows, key, results_dir=RESULTS, force=False):
    sheet_path, key_path = Path(results_dir) / "judge_sheet.csv", Path(results_dir) / "answer_key.json"
    page_path = Path(results_dir) / "judge.html"
    if sheet_path.exists() and not force:
        raise SystemExit(f"{sheet_path} 已經存在（裡面可能有填好的判讀），不覆蓋。真的要重做請加 --force。")
    page_path.write_text(build_page(rows), encoding="utf-8")
    # utf-8-sig：Excel 才認得出是 UTF-8，中文不會變亂碼
    with open(sheet_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    with open(key_path, "w", encoding="utf-8") as f:
        json.dump(key, f, ensure_ascii=False, indent=2)
    return sheet_path, key_path


def main_cli():
    parser = argparse.ArgumentParser(description="產生反思機制實驗的人工判讀表")
    parser.add_argument("--force", action="store_true", help="判讀表已經存在也重新產生（會蓋掉填好的內容）")
    parser.add_argument("--blind", action="store_true",
                        help="盲測：每題隨機排成 A／B（預設 A 固定是無反思、B 固定是有反思）")
    args = parser.parse_args()
    scenarios, raw = load_scenarios(), load_raw()
    missing = [s["id"] for s in scenarios if s["id"] not in raw]
    if missing:
        print(f"注意：還有 {len(missing)} 題沒跑完（{'、'.join(missing)}），判讀表先不含這些題目。")
    rows, key = build_sheet(scenarios, raw, blind=args.blind)
    sheet_path, _ = write_sheet(rows, key, force=args.force)
    changed = sum(1 for v in key.values() if v != "same")
    print(f"共 {len(rows)} 題，其中 {changed} 題的回覆A、B 不一樣（反思機制改寫過）。")
    if args.blind:
        print("盲測：A／B 是隨機排的，判讀的人不要打開 answer_key.json。")
    else:
        print("回覆A＝無反思（原稿）、回覆B＝有反思（最後回覆）。判讀的人知道哪個是哪個，不是盲測，專刊要寫明。")
    print(f"已產生判讀網頁：{sheet_path.parent / 'judge.html'}  ← 用瀏覽器打開，一題一題勾選")
    print(f"（同樣內容的 Excel 版：{sheet_path}，不太好讀，建議用網頁）")
    print("判讀完按網頁右上角「匯出成 CSV」，再執行：py experiments/reflection_eval/score.py 匯出的檔案.csv")


if __name__ == "__main__":
    main_cli()
