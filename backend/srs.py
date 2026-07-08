"""
SRS 间隔复习引擎（严格按 PRD §4.1 / §4.3 / §4.5）。

规则要点：
- 四档评分间隔变化（均向上取整为整数天）：
    Again → 重置为 1 天（次日再现）
    Hard  → 当前间隔 × 1.2（向上取整，最少 +1 天）
    Good  → 当前间隔 × 2.5（向上取整，标准增长）
    Easy  → 当前间隔 × 3.0（向上取整，MVP 取 3.0）
- 间隔钳制：[1, 180] 天（最小 1 天；超过 180 视为长期记忆，不再频繁调度）。
- 新词首次间隔（学习阶段，非乘算）：
    认识(know) → 4 天；不熟/不会(fuzzy/never) → 1 天。
- 掌握度分层（§2.6 / §4.3）：
    new       : 尚未完成首次复习（reps==0）
    familiar  : 完成 1-2 次复习，间隔 < 7 天
    mastered  : 完成 3+ 次复习，间隔 ≥ 7 天
    longterm  : 间隔 ≥ 30 天 且 近 3 次无 Again（用 lapses==0 近似）
- 生词毕业：SRS 复习中连续 3 次评 Good → 自动移出生词本。
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

import math

# 各档位间隔倍数（Again 为重置，无倍数）
GRADE_MULTIPLIER = {
    "again": None,
    "hard": 1.2,
    "good": 2.5,
    "easy": 3.0,
}

MIN_INTERVAL = 1
MAX_INTERVAL = 180

# 新词首次曝光按「熟悉度」设定的首间隔（天）
NEW_WORD_FIRST_INTERVAL = {
    "known": 4,   # 认识
    "fuzzy": 1,   # 不熟
    "never": 1,   # 不会
}

# 新词首次曝光映射到复习流水 grade（用于统计）
NEW_WORD_GRADE = {
    "known": "easy",
    "fuzzy": "hard",
    "never": "again",
}


def _ceil_interval(value: float) -> int:
    return max(MIN_INTERVAL, min(MAX_INTERVAL, int(math.ceil(value))))


def next_interval(current_interval: int, grade: str) -> int:
    """根据评分计算下一次复习间隔（天）。current_interval 为当前间隔。"""
    if grade == "again":
        return MIN_INTERVAL  # 重置为 1 天
    mult = GRADE_MULTIPLIER[grade]
    new = current_interval * mult
    if grade == "hard":
        # Hard 最少 +1 天（PRD §4.1 备注）
        new = max(new, current_interval + 1)
    return _ceil_interval(new)


def compute_level(reps: int, interval_days: int, lapses: int) -> str:
    """掌握度分层（§2.6）。"""
    if reps == 0:
        return "new"
    if interval_days >= 30 and lapses == 0:
        return "longterm"
    if reps >= 3 and interval_days >= 7:
        return "mastered"
    if reps >= 1:
        return "familiar"
    return "new"


def apply_grade(
    *,
    current_interval: int,
    reps: int,
    lapses: int,
    consecutive_good: int,
    grade: str,
    now: datetime | None = None,
) -> Dict:
    """应用一次评分，返回更新后的 SRS 字段字典。

    返回字段：interval_days, reps, lapses, consecutive_good, level, due_date, graduated
    graduated=True 表示本次触发「连续 3 次 Good 毕业」。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    new_interval = next_interval(current_interval, grade)

    if grade == "again":
        new_reps = 0
        new_lapses = lapses + 1
        new_consecutive_good = 0
    else:
        new_reps = reps + 1
        new_lapses = lapses
        new_consecutive_good = consecutive_good + 1 if grade == "good" else 0

    new_level = compute_level(new_reps, new_interval, new_lapses)
    due_date = now + timedelta(days=new_interval)
    graduated = new_consecutive_good >= 3

    return {
        "interval_days": new_interval,
        "reps": new_reps,
        "lapses": new_lapses,
        "consecutive_good": new_consecutive_good,
        "level": new_level,
        "due_date": due_date,
        "graduated": graduated,
    }


def new_word_mastery(familiarity: str, now: datetime | None = None) -> Dict:
    """新词首次曝光：按熟悉度设定首间隔与初始状态。"""
    if now is None:
        now = datetime.now(timezone.utc)
    interval = NEW_WORD_FIRST_INTERVAL.get(familiarity, 1)
    grade = NEW_WORD_GRADE.get(familiarity, "again")
    level = compute_level(0, interval, 0)
    return {
        "interval_days": interval,
        "reps": 0,
        "lapses": 0,
        "consecutive_good": 0,
        "level": level,
        "due_date": now + timedelta(days=interval),
        "grade": grade,
    }
