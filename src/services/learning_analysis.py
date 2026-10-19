# -*- coding: utf-8 -*-
"""
src/services/learning_analysis.py
功能簡介：學習歷程的蒐集與分析。
  1. 標記（tag_turn）：每一輪問答送出後，在背景請 Gemini 標出這一輪的單元、觀念、學生在做什麼
     （觀念提問／題目求助／作答／卡住）、作答對不對、錯在哪、在解哪一題、是不是解出來了。
     單元只能從 src/curriculum.py 的清單挑，統計才不會因為寫法不同而被拆散。
  2. 報告（build_report / build_overview）：把標記和訊息時間整理成學習紀錄頁、管理後台要看的數字。
     這兩個是純函式（不碰資料庫、不呼叫 AI），給什麼資料就算什麼，方便測試。
  3. 建議（write_advice）：學生按按鈕時，請 Gemini 依報告寫一段學習建議。
注意：標記是 AI 判斷的，不會百分之百準，比較適合看趨勢；頁面上也有這樣提醒學生。
主要函數：
  - tag_turn(call_gemini, student_message, reply, previous_reply, previous_event) -> dict
  - build_report(events, message_times, now=None) -> dict
  - build_overview(usernames, events, message_times, now=None) -> dict
  - has_enough_data(report) / write_advice(call_gemini, report) -> str
相依模組：pydantic、google.genai.types、src.curriculum
"""

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from google.genai import types
from pydantic import BaseModel

from src import curriculum

ACTIVITIES = ("觀念提問", "題目求助", "作答", "卡住", "其他")
RESULTS = ("正確", "部分正確", "錯誤")
ERROR_TYPES = ("計算錯誤", "觀念錯誤", "看錯題目", "其他")
_MISTAKES = ("錯誤", "部分正確")

# 台灣時間（沒有日光節約）：資料庫存 UTC，算「哪一天、哪一週」要換成當地時間
_LOCAL_TZ = timezone(timedelta(hours=8))
# 估算學習時間：兩則訊息隔超過這麼久就算另一次；每次最後再加幾分鐘看老師的回覆
_SESSION_GAP = timedelta(minutes=20)
_READING_MINUTES = 3
_WEEKS_SHOWN = 8
# 超過這麼多天沒來，就列進管理後台的「很久沒上線」
_INACTIVE_DAYS = 7
# 至少要有這麼多筆標記才寫學習建議，太少寫出來也不準
_MIN_EVENTS_FOR_ADVICE = 3
# 背景標記每次呼叫最多等這麼久
_TAG_TIMEOUT_MS = 60_000

TAG_INSTRUCTION = """你是國中數學學習紀錄的分析員。請根據下面這一輪師生對話，標記學生這一輪的學習狀況。

單元清單（unit 只能填清單裡的代號，例如「8上 3-2」；跟國中數學無關、或判斷不出來就填空字串）：
{units}

欄位說明：
- unit：這一輪在學的單元代號。
- concept：這一輪最相關的具體觀念或技巧，12 個字以內，例如「畢氏定理」「十字交乘法」。
  學生答錯或卡住時，寫出錯在、卡在哪個觀念或技巧（例如「移項要變號」「十字交乘法的正負號」），不要只寫大單元名稱。
  跟這個學生之前標過的觀念是同一個時，照抄之前的寫法，統計才不會被拆散。之前標過的觀念：{known_concepts}
  沒有就填空字串。
- activity：學生這一輪在做什麼，只能填其中一個：
  「觀念提問」問定義、公式、為什麼；「題目求助」拿一道題來問怎麼解；「作答」回答老師的提問、或算出答案；
  「卡住」說不會、不知道、要提示；「其他」打招呼、閒聊、跟數學無關。
- result：activity 是「作答」時填「正確」「部分正確」「錯誤」，其他情況填空字串。可以參考老師的回覆怎麼評論學生的答案。
- error_type：result 是「錯誤」或「部分正確」時填「計算錯誤」「觀念錯誤」「看錯題目」「其他」，其他情況填空字串。
- problem：學生正在解的那一道題，20 個字以內，例如「解 x²−5x+6=0」；沒有在解題就填空字串。
- same_problem：這一輪是不是還在解上一輪那一題（上一輪的題目：{previous_problem}）。
- solved：這一輪學生是不是已經自己得到這一題正確的最終答案。"""

ADVICE_INSTRUCTION = """你是國中數學老師，要根據學生的學習紀錄，寫一段給學生本人看的學習建議。
要求：
- 用繁體中文、親切鼓勵的語氣，直接對學生說話（用「你」）。
- 先用一兩句肯定學生做得好的地方（例如常來練習、某個單元答對率高）。
- 再指出 1～3 個最需要加強的單元或觀念，說明為什麼（根據紀錄裡答錯、卡住的情形），並給具體的練習方法；
  提到單元時寫出冊別和單元名稱（例如「8上的利用十字交乘法因式分解」），學生才找得到自己課本裡的那一課；
  不要寫 3-2 這類章節編號，也不要提頁碼：每個學生用的課本版本不一樣，編號對不上。
- 最後一句鼓勵。
- 全部 250 字以內；不要用 LaTeX、不要用表格，可以用「- 」開頭的條列。
- 只根據下面的紀錄說話，紀錄裡沒有的事不要編；提到天數、次數時要跟紀錄一模一樣。

學生的學習紀錄：
{summary}"""


class TurnTag(BaseModel):
    unit: str
    concept: str
    activity: str
    result: str
    error_type: str
    problem: str
    same_problem: bool
    solved: bool


# ============================== 標記 ==============================

def _pick(value: str, allowed, default: str = "") -> str:
    value = (value or "").strip()
    return value if value in allowed else default


def normalize_tag(tag: TurnTag, previous_event: Optional[dict]) -> dict:
    """把 AI 的標記整理成固定的值（單元對得上清單、選項在範圍內），並決定這一輪屬於哪一題。"""
    activity = _pick(tag.activity, ACTIVITIES, "其他")
    result = _pick(tag.result, RESULTS) if activity == "作答" else ""
    error_type = _pick(tag.error_type, ERROR_TYPES, "其他") if result in _MISTAKES else ""
    problem = (tag.problem or "").strip()[:30]
    previous_id = (previous_event or {}).get("problem_id") or ""
    # 同一題沿用上一輪的編號，不然開一個新的；沒在解題就沒有編號
    if tag.same_problem and previous_id:
        problem_id = previous_id
        problem = problem or (previous_event or {}).get("problem", "")
    else:
        problem_id = uuid.uuid4().hex[:12] if problem else ""
    return {
        "unit": curriculum.normalize_unit(tag.unit),
        "concept": (tag.concept or "").strip()[:20],
        "activity": activity,
        "result": result,
        "error_type": error_type,
        "problem_id": problem_id,
        "problem": problem,
        "solved": bool(tag.solved and problem_id),
    }


def known_concepts(events: List[dict], limit: int = 30) -> List[str]:
    """這個學生最近標過的觀念（不重複，新的在前），給標記時沿用同一種寫法。"""
    return list(dict.fromkeys(e["concept"] for e in reversed(events) if e["concept"]))[:limit]


def tag_turn(call_gemini: Callable, student_message: str, reply: str, previous_reply: str,
             previous_event: Optional[dict], concepts: List[str] = ()) -> dict:
    """
    請 Gemini 標記這一輪，回傳整理好的標記。call_gemini(contents, gen_config) 由 main.py 傳進來；
    concepts 是這個學生之前標過的觀念（見 known_concepts）。
    """
    previous_problem = (previous_event or {}).get("problem") or "（沒有）"
    contents = (
        TAG_INSTRUCTION.format(units=curriculum.units_prompt(), previous_problem=previous_problem,
                               known_concepts="、".join(concepts) or "（還沒有）")
        + f"\n\n【老師上一輪說的話】\n{(previous_reply or '（這是對話的第一句）')[:800]}"
        + f"\n\n【學生這一輪說的話】\n{student_message}"
        + f"\n\n【老師這一輪的回覆】\n{(reply or '')[:1500]}"
    )
    result = call_gemini(
        contents,
        types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=TurnTag, temperature=0,
            # 在背景做，不急；但也不能一直卡著佔住伺服器的執行緒（實測模型偶爾會卡好幾分鐘）
            http_options=types.HttpOptions(timeout=_TAG_TIMEOUT_MS),
        ),
    )
    parsed = getattr(result, "parsed", None)
    tag = parsed if isinstance(parsed, TurnTag) else TurnTag.model_validate_json(result.text)
    return normalize_tag(tag, previous_event)


# ============================== 報告 ==============================

def _parse_utc(value: str) -> datetime:
    """資料庫的時間（UTC，YYYY-MM-DD HH:MM:SS）→ 帶時區的 datetime。"""
    return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _neg_time(value: Optional[str]) -> float:
    """排序用：時間越新排越前面。"""
    return -_parse_utc(value).timestamp() if value else 0.0


def _sessions(times: List[datetime]) -> List[tuple]:
    """把訊息時間切成一次一次的學習：隔超過 _SESSION_GAP 就算新的一次。回傳 [(開始, 分鐘數), ...]。"""
    sessions = []
    start = last = None
    for t in times:
        if start is None or t - last > _SESSION_GAP:
            if start is not None:
                sessions.append((start, (last - start).total_seconds() / 60 + _READING_MINUTES))
            start = t
        last = t
    if start is not None:
        sessions.append((start, (last - start).total_seconds() / 60 + _READING_MINUTES))
    return sessions


def usage_stats(times: List[datetime], now: datetime) -> dict:
    """使用情形：學習天數、提問次數、估計學習時間（總共和近 7 天）、最後上線、近 8 週每週的量。"""
    week_ago = now - timedelta(days=7)
    sessions = _sessions(times)
    today = now.astimezone(_LOCAL_TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    weeks = []
    for i in range(_WEEKS_SHOWN - 1, -1, -1):
        monday = this_monday - timedelta(weeks=i)
        in_week = lambda t: monday <= t.astimezone(_LOCAL_TZ).date() < monday + timedelta(weeks=1)
        weeks.append({
            "label": f"{monday.month}/{monday.day}",
            "questions": sum(1 for t in times if in_week(t)),
            "minutes": round(sum(m for s, m in sessions if in_week(s))),
        })
    return {
        "active_days": len({t.astimezone(_LOCAL_TZ).date() for t in times}),
        "questions": len(times),
        "questions_7d": sum(1 for t in times if t >= week_ago),
        "minutes": round(sum(m for _, m in sessions)),
        "minutes_7d": round(sum(m for s, m in sessions if s >= week_ago)),
        "last_active": max(times).strftime("%Y-%m-%d %H:%M:%S") if times else None,
        "weeks": weeks,
    }


def _problems(events: List[dict]) -> Dict[str, List[dict]]:
    """依題目編號把標記分組（同一題來回好幾輪），保持先後順序。"""
    problems = defaultdict(list)
    for e in events:
        if e.get("problem_id"):
            problems[e["problem_id"]].append(e)
    return problems


def _turns_to_solve(problem_events: List[dict]) -> Optional[int]:
    """這一題學生來回幾輪才解出來；還沒解出來回傳 None。"""
    for i, e in enumerate(problem_events):
        if e.get("solved"):
            return i + 1
    return None


def _average(values) -> Optional[float]:
    values = list(values)
    return round(sum(values) / len(values), 1) if values else None


def _practice(events: List[dict]) -> dict:
    """作答與解題的統計（整體或某一個單元）。"""
    attempts = [e for e in events if e["activity"] == "作答"]
    counts = Counter(e["result"] for e in attempts)
    solve_turns = [t for t in map(_turns_to_solve, _problems(events).values()) if t is not None]
    stats = {
        "turns": len(events),
        "attempts": len(attempts),
        "correct": counts["正確"],
        "partial": counts["部分正確"],
        "wrong": counts["錯誤"],
        "stuck": sum(1 for e in events if e["activity"] == "卡住"),
        "accuracy": round(counts["正確"] / len(attempts), 2) if attempts else None,
        "problems": len(_problems(events)),
        "solved": len(solve_turns),
        "avg_turns_to_solve": _average(solve_turns),
    }
    # 需要加強的程度：答錯一次算 1、部分正確算 0.5、卡住算 1
    stats["weakness"] = stats["wrong"] + 0.5 * stats["partial"] + stats["stuck"]
    return stats


def _weak_reasons(stats: dict) -> str:
    parts = []
    if stats["wrong"]:
        parts.append(f"答錯 {stats['wrong']} 次")
    if stats["partial"]:
        parts.append(f"部分正確 {stats['partial']} 次")
    if stats["stuck"]:
        parts.append(f"卡住 {stats['stuck']} 次")
    if stats["accuracy"] is not None:
        parts.append(f"答對率 {round(stats['accuracy'] * 100)}%")
    return "、".join(parts)


def unit_stats(events: List[dict]) -> List[dict]:
    """每個單元的統計，問得越多的排越前面。沒標到單元的不算。"""
    by_unit = defaultdict(list)
    for e in events:
        if e["unit"]:
            by_unit[e["unit"]].append(e)
    units = [{"unit": unit, "title": curriculum.unit_title(unit), **_practice(unit_events)}
             for unit, unit_events in by_unit.items()]
    return sorted(units, key=lambda u: (-u["turns"], u["unit"]))


def weak_units(units: List[dict], limit: int = 3) -> List[dict]:
    """需要加強的單元：答錯、卡住越多越前面；一樣多就看答對率。"""
    weak = [u for u in units if u["weakness"] >= 1]
    weak.sort(key=lambda u: (-u["weakness"], u["accuracy"] if u["accuracy"] is not None else 1))
    return [{**u, "reasons": _weak_reasons(u)} for u in weak[:limit]]


def build_report(events: List[dict], message_times: List[str], now: Optional[datetime] = None) -> dict:
    """
    一個學生的學習紀錄。events 是 learning_store 的標記（依時間排序），message_times 是學生每則訊息的
    UTC 時間字串。回傳給學習紀錄頁（和管理後台看單一學生時）用的 JSON。
    """
    now = now or datetime.now(timezone.utc)
    mistakes = [e for e in events if e["result"] in _MISTAKES or e["activity"] == "卡住"]

    concepts: Dict[str, dict] = {}
    for e in mistakes:
        if not e["concept"]:
            continue
        item = concepts.setdefault(e["concept"], {"concept": e["concept"], "count": 0})
        item.update(count=item["count"] + 1, unit=e["unit"], title=curriculum.unit_title(e["unit"]),
                    last_at=e["created_at"], conversation_id=e["conversation_id"])
    # 次數多的排前面；一樣多就最近的排前面
    weak_concepts = sorted(concepts.values(), key=lambda c: (-c["count"], _neg_time(c["last_at"])))

    units = unit_stats(events)
    return {
        "usage": usage_stats([_parse_utc(t) for t in message_times], now),
        "practice": _practice(events),
        "units": units,
        "weak_units": weak_units(units),
        "weak_concepts": weak_concepts[:5],
        "error_types": [{"type": t, "count": n} for t, n in
                        Counter(e["error_type"] for e in events if e["error_type"]).most_common()],
        "recent_mistakes": [
            {"at": e["created_at"], "unit": e["unit"], "title": curriculum.unit_title(e["unit"]),
             "concept": e["concept"], "problem": e["problem"], "result": e["result"],
             "error_type": e["error_type"], "conversation_id": e["conversation_id"]}
            for e in reversed([e for e in events if e["result"] in _MISTAKES])
        ][:5],
        "event_count": len(events),
    }


def build_overview(usernames: List[str], events: List[dict], message_times: List[tuple],
                   now: Optional[datetime] = None) -> dict:
    """
    管理後台的全班總覽。usernames 是所有帳號；events 是所有人的標記（帶 username）；
    message_times 是 [(帳號, UTC 時間字串), ...]。
    """
    now = now or datetime.now(timezone.utc)
    events_by_user = defaultdict(list)
    for e in events:
        events_by_user[e["username"]].append(e)
    times_by_user = defaultdict(list)
    for username, t in message_times:
        times_by_user[username].append(_parse_utc(t))

    students = []
    for username in usernames:
        usage = usage_stats(times_by_user[username], now)
        practice = _practice(events_by_user[username])
        weak = weak_units(unit_stats(events_by_user[username]), limit=1)
        students.append({
            "username": username,
            "last_active": usage["last_active"],
            "questions": usage["questions"],
            "questions_7d": usage["questions_7d"],
            "minutes_7d": usage["minutes_7d"],
            "attempts": practice["attempts"],
            "accuracy": practice["accuracy"],
            "weak_unit": {"unit": weak[0]["unit"], "title": weak[0]["title"]} if weak else None,
        })
    students.sort(key=lambda s: _neg_time(s["last_active"]) if s["last_active"] else 1.0)

    # 全班每個單元：幾個人問過、答錯卡住幾次、有幾個人在這個單元需要加強
    units = unit_stats(events)
    for unit in units:
        per_student = [unit_stats([e for e in user_events if e["unit"] == unit["unit"]])
                       for user_events in events_by_user.values()]
        unit["students"] = sum(1 for s in per_student if s)
        unit["struggling"] = sum(1 for s in per_student if s and s[0]["weakness"] >= 1)
    units.sort(key=lambda u: (-u["weakness"], -u["turns"]))

    inactive_before = now - timedelta(days=_INACTIVE_DAYS)
    overall = _practice(events)
    return {
        "totals": {
            "students": len(usernames),
            "active_7d": sum(1 for s in students if s["questions_7d"]),
            "questions_7d": sum(s["questions_7d"] for s in students),
            "accuracy": overall["accuracy"],
            "attempts": overall["attempts"],
        },
        "units": units[:10],
        "students": students,
        "inactive": [{"username": s["username"], "last_active": s["last_active"]} for s in students
                     if not s["last_active"] or _parse_utc(s["last_active"]) < inactive_before],
    }


# ============================== 建議 ==============================

def has_enough_data(report: dict) -> bool:
    return report.get("event_count", 0) >= _MIN_EVENTS_FOR_ADVICE


def _percent(value: Optional[float]) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def summarize_for_advice(report: dict) -> str:
    """把報告整理成給 AI 看的文字（只有數字和單元、觀念名稱，不含對話內容）。"""
    usage, practice = report["usage"], report["practice"]
    lines = [
        f"學習天數 {usage['active_days']} 天，提問 {usage['questions']} 次（近 7 天 {usage['questions_7d']} 次），"
        f"估計學習時間 {usage['minutes']} 分鐘。",
        f"作答 {practice['attempts']} 次：答對 {practice['correct']}、部分正確 {practice['partial']}、答錯 {practice['wrong']}，"
        f"答對率 {_percent(practice['accuracy'])}；說自己卡住 {practice['stuck']} 次。",
        f"解題 {practice['problems']} 題，解出 {practice['solved']} 題"
        + (f"，平均來回 {practice['avg_turns_to_solve']} 輪解出。" if practice["avg_turns_to_solve"] else "。"),
        "",
        "各單元（問的次數、作答、答錯、卡住、答對率）：",
    ]
    for u in report["units"][:8]:
        lines.append(f"- {u['unit']} {u['title']}：問 {u['turns']} 次，作答 {u['attempts']}，答錯 {u['wrong']}，"
                     f"卡住 {u['stuck']}，答對率 {_percent(u['accuracy'])}")
    if report["weak_concepts"]:
        lines += ["", "常出錯或卡住的觀念："]
        lines += [f"- {c['concept']}（{c['unit']} {c['title']}）{c['count']} 次" for c in report["weak_concepts"]]
    if report["error_types"]:
        lines += ["", "錯誤類型：" + "、".join(f"{t['type']} {t['count']} 次" for t in report["error_types"])]
    return "\n".join(lines)


def write_advice(call_gemini: Callable, report: dict) -> str:
    """請 Gemini 依學習紀錄寫學習建議。call_gemini(contents) 由 main.py 傳進來。"""
    result = call_gemini(ADVICE_INSTRUCTION.format(summary=summarize_for_advice(report)))
    advice = (result.text or "").strip()
    if not advice:
        raise ValueError("模型沒有回傳學習建議")
    return advice
