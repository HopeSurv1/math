# -*- coding: utf-8 -*-
"""
experiments/reflection_eval/score.py
功能簡介：反思機制實驗的第 3 步——讀填好的判讀表，對照 answer_key.json，算出專刊表格的 5 項數據：
            直接給答案、數學錯誤、與課本不一致：無反思（原稿）／有反思（最後回覆）各有幾題被判讀為有這個問題
            誤改：原稿三項都沒問題，反思機制卻還是改寫了（另外列出改完反而出問題的題目）
            平均回覆時間：有反思 ＝ 整輪秒數；無反思 ＝ 整輪秒數扣掉反思機制花的秒數
使用方式：py experiments/reflection_eval/score.py                         讀 results/judge_sheet.csv
          py experiments/reflection_eval/score.py 判讀表.csv              讀指定的判讀表（例如另一位組員填的）
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NO_REVIEW, RESULTS, WITH_REVIEW, load_raw  # noqa: E402
from make_sheet import KINDS  # noqa: E402

_YES = {"1", "v", "y", "是", "有", "✓", "○", "o"}
_NO = {"", "0", "n", "否", "無", "-"}


def read_sheet(path):
    """Excel 存成「CSV UTF-8」或一般「CSV」（Big5）都讀得懂。"""
    for encoding in ("utf-8-sig", "cp950"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"讀不懂 {path} 的編碼，請在 Excel 另存成「CSV UTF-8（逗號分隔）」")


def _mark(value, where, problems):
    value = (value or "").strip().lower()
    if value in _YES:
        return True
    if value not in _NO:
        problems.append(f"{where} 填了「{value}」，看不懂（有問題填 1、沒問題留空）")
    return False


def score(rows, key, raw):
    """回傳統計結果 dict；判讀表裡看不懂的格子列在 result["warnings"]。"""
    warnings = []
    judged = {}  # 題號 → {NO_REVIEW: {問題: bool}, WITH_REVIEW: {...}}
    for row in rows:
        qid = (row.get("題號") or "").strip()
        if qid not in key or qid not in raw:
            if qid:
                warnings.append(f"{qid} 不在答案卷或實驗結果裡，略過")
            continue
        marks_a = {k: _mark(row.get(f"A{k}"), f"{qid} 的 A{k}", warnings) for k in KINDS}
        marks_b = {k: _mark(row.get(f"B{k}"), f"{qid} 的 B{k}", warnings) for k in KINDS}
        if key[qid] == "same":
            judged[qid] = {NO_REVIEW: marks_a, WITH_REVIEW: marks_a}
        else:
            judged[qid] = {key[qid]["A"]: marks_a, key[qid]["B"]: marks_b}

    n = len(judged)
    counts = {version: {k: sum(j[version][k] for j in judged.values()) for k in KINDS}
              for version in (NO_REVIEW, WITH_REVIEW)}
    rewritten = [qid for qid in judged if key[qid] != "same"]
    needless = [qid for qid in rewritten if not any(judged[qid][NO_REVIEW].values())]
    made_worse = [qid for qid in needless if any(judged[qid][WITH_REVIEW].values())]
    fixed = [qid for qid in rewritten if any(judged[qid][NO_REVIEW].values())
             and not any(judged[qid][WITH_REVIEW].values())]
    # 把反思機制當成「檢查員」看：原稿真的有問題的題目，它抓到幾題、漏掉幾題；它動手改寫的題目，有幾題真的需要
    real = [qid for qid in judged if any(judged[qid][NO_REVIEW].values())]
    caught = [qid for qid in real if qid in rewritten]
    missed = [qid for qid in real if qid not in rewritten]
    totals = [raw[qid]["total_seconds"] for qid in judged]
    reviews = [raw[qid]["review_seconds"] for qid in judged]
    avg = (lambda xs: round(sum(xs) / len(xs), 1) if xs else 0.0)
    return {
        "n": n, "counts": counts, "rewritten": rewritten, "needless": needless,
        "made_worse": made_worse, "fixed": fixed,
        "reviewer": {"real": real, "caught": caught, "missed": missed, "rewritten": rewritten},
        "seconds": {NO_REVIEW: avg([t - r for t, r in zip(totals, reviews)]), WITH_REVIEW: avg(totals)},
        "by_type": _by_type(judged, raw), "warnings": warnings,
    }


def _by_type(judged, raw):
    """各類型題目中，有任何一項問題的題數（無反思／有反思），寫內文時參考。"""
    table = {}
    for qid, versions in judged.items():
        row = table.setdefault(raw[qid]["type"], {"n": 0, NO_REVIEW: 0, WITH_REVIEW: 0})
        row["n"] += 1
        for version in (NO_REVIEW, WITH_REVIEW):
            row[version] += any(versions[version].values())
    return table


def report(result):
    n, c = result["n"], result["counts"]
    lines = [f"共判讀 {n} 題，其中反思機制改寫過的有 {len(result['rewritten'])} 題。", "",
             "| | 直接給答案 | 數學錯誤 | 與課本不一致 | 誤改 | 平均回覆時間 |",
             "|---|---|---|---|---|---|",
             f"| 無反思 | {c[NO_REVIEW]['直接給答案']}／{n} | {c[NO_REVIEW]['數學錯誤']} | "
             f"{c[NO_REVIEW]['與課本不一致']} | — | {result['seconds'][NO_REVIEW]} 秒 |",
             f"| 有反思 | {c[WITH_REVIEW]['直接給答案']}／{n} | {c[WITH_REVIEW]['數學錯誤']} | "
             f"{c[WITH_REVIEW]['與課本不一致']} | {len(result['needless'])} | {result['seconds'][WITH_REVIEW]} 秒 |",
             "",
             f"改寫後問題消失：{len(result['fixed'])} 題 {_ids(result['fixed'])}",
             f"誤改（原稿沒問題卻被改寫）：{len(result['needless'])} 題 {_ids(result['needless'])}",
             f"　其中改完反而出問題：{len(result['made_worse'])} 題 {_ids(result['made_worse'])}",
             "", "把反思機制當成檢查員來看（是不是「過度反思」）："]
    r = result["reviewer"]
    lines += [f"　原稿真的有問題：{len(r['real'])} 題；反思機制抓到 {len(r['caught'])} 題、漏掉 {len(r['missed'])} 題 {_ids(r['missed'])}",
              f"　它動手改寫 {len(r['rewritten'])} 題，其中 {len(r['caught'])} 題原稿真的有問題、"
              f"{len(r['rewritten']) - len(r['caught'])} 題原稿其實沒問題（誤改）",
              f"　改寫的準確率：{_ratio(len(r['caught']), len(r['rewritten']))}（改寫的題目中，原稿真的有問題的比例）",
              f"　抓到率：{_ratio(len(r['caught']), len(r['real']))}（有問題的題目中，被反思機制抓到的比例）",
              "", "各類型「有任何一項問題」的題數（無反思 → 有反思）："]
    for kind, row in result["by_type"].items():
        lines.append(f"　{kind}（{row['n']} 題）：{row[NO_REVIEW]} → {row[WITH_REVIEW]}")
    if result["warnings"]:
        lines += ["", "注意，判讀表有看不懂的地方（這些格子當成「沒問題」計算）："]
        lines += [f"　{w}" for w in result["warnings"]]
    return "\n".join(lines)


def _ratio(part, whole):
    return f"{part}／{whole}（{part / whole:.0%}）" if whole else "—（沒有可以算的題目）"


def _ids(ids):
    return f"（{'、'.join(ids)}）" if ids else ""


def main_cli():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="讀判讀表，算出專刊表格的 5 項數據")
    parser.add_argument("sheet", nargs="?", default=str(RESULTS / "judge_sheet.csv"), help="判讀表 CSV（預設 results/judge_sheet.csv）")
    parser.add_argument("--key", default=str(RESULTS / "answer_key.json"),
                        help="答案卷（預設 results/answer_key.json；判讀表是用別的排法產生時才需要指定）")
    args = parser.parse_args()
    sheet, key_path = Path(args.sheet), Path(args.key)
    if not sheet.exists() or not key_path.exists():
        raise SystemExit("找不到判讀表或答案卷：請先執行 make_sheet.py，判讀完再算分")
    with open(key_path, encoding="utf-8") as f:
        key = json.load(f)
    print(report(score(read_sheet(sheet), key, load_raw())))


if __name__ == "__main__":
    main_cli()
