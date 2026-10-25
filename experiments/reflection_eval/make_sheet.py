import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NO_REVIEW, RESULTS, WITH_REVIEW, load_raw, load_scenarios

SEED = 20261001
SAME = "（與回覆A相同，只要判讀A）"
KINDS = ("直接給答案", "數學錯誤", "與課本不一致")
COLUMNS = (["題號", "類型", "判讀提示", "先前對話", "學生這句", "回覆A"] + [f"A{k}" for k in KINDS]
           + ["回覆B"] + [f"B{k}" for k in KINDS] + ["備註"])
_ROLE = {"user": "學生", "model": "老師"}

def build_sheet(scenarios, raw, seed=SEED, blind=False):
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
    data = {"columns": COLUMNS, "kinds": list(KINDS), "same": SAME, "rows": rows,
            "fingerprint": hashlib.sha1(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template = (Path(__file__).resolve().parent / "judge_template.html").read_text(encoding="utf-8")
    return template.replace("__DATA__", payload)

def write_sheet(rows, key, results_dir=RESULTS, force=False):
    sheet_path, key_path = Path(results_dir) / "judge_sheet.csv", Path(results_dir) / "answer_key.json"
    page_path = Path(results_dir) / "judge.html"
    if sheet_path.exists() and not force:
        raise SystemExit(f"{sheet_path} 已經存在（裡面可能有填好的判讀），不覆蓋。真的要重做請加 --force。")
    page_path.write_text(build_page(rows), encoding="utf-8")
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
