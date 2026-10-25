import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

NO_REVIEW = "無反思"
WITH_REVIEW = "有反思"

def load_scenarios():
    with open(HERE / "scenarios.json", encoding="utf-8") as f:
        return json.load(f)


def load_raw(results_dir=RESULTS):
    path = Path(results_dir) / "raw.jsonl"
    records = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records[record["id"]] = record
    return records
