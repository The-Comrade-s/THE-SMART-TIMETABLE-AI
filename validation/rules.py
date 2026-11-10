"""Reusable field validators with clear messages."""
from __future__ import annotations

import re
from datetime import time

from database.enums import AVAILABILITY, LEVELS, ROOM_TYPES, SEMESTERS
from services.common import ValidationError

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_SESSION = re.compile(r"^(\d{4})/(\d{4})$")


def validate_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 255:
        raise ValidationError("Enter a valid email address.")
    return e


def validate_academic_session(value: str) -> str:
    v = (value or "").strip()
    m = _SESSION.match(v)
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        raise ValidationError("Academic session must look like 2025/2026.")
    return v


def validate_level(level) -> int:
    try:
        lv = int(level)
    except (TypeError, ValueError):
        raise ValidationError("Academic level must be a number.")
    if lv not in LEVELS:
        raise ValidationError(f"Academic level must be one of {', '.join(map(str, LEVELS))}.")
    return lv


def validate_semester(value: str) -> str:
    if value not in SEMESTERS:
        raise ValidationError("Semester must be FIRST or SECOND.")
    return value


def validate_room_type(value: str) -> str:
    if value not in ROOM_TYPES:
        raise ValidationError("Select a valid room type.")
    return value


def validate_positive_int(value, label: str, maximum: int | None = None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a whole number.")
    if n <= 0:
        raise ValidationError(f"{label} must be greater than zero.")
    if maximum is not None and n > maximum:
        raise ValidationError(f"{label} must be at most {maximum}.")
    return n


def validate_interval(start: time, end: time, label: str = "Time period") -> None:
    if start is None or end is None or start >= end:
        raise ValidationError(f"{label}: the end time must be later than the start time.")


def validate_day(day) -> int:
    if not isinstance(day, int) or not 0 <= day <= 6:
        raise ValidationError("Day of week must be between Monday and Sunday.")
    return day


def validate_availability_status(value: str) -> str:
    if value not in AVAILABILITY:
        raise ValidationError("Availability status must be AVAILABLE, PREFERRED or UNAVAILABLE.")
    return value


def to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def from_minutes(m: int) -> time:
    return time(m // 60, m % 60)


def fmt_time(t: time) -> str:
    return t.strftime("%H:%M")
