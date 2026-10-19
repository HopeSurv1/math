# -*- coding: utf-8 -*-
"""
experiments/reflection_eval/common.py
功能簡介：反思機制實驗三支腳本共用的路徑與讀檔函式（不 import src，產生判讀表、計分時不用載入整個後端）。
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# 反思機制開／關兩個版本的名稱
NO_REVIEW = "無反思"
WITH_REVIEW = "有反思"


def load_scenarios():
    """scenarios.json：[{id, type, hint, history: [[role, text], ...], message}, ...]"""
    with open(HERE / "scenarios.json", encoding="utf-8") as f:
        return json.load(f)


def load_raw(results_dir=RESULTS):
    """results/raw.jsonl：一行一題的實驗結果；同一題跑過好幾次以最後一次為準。回傳 {題號: 紀錄}。"""
    path = Path(results_dir) / "raw.jsonl"
    records = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records[record["id"]] = record
    return records
