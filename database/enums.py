"""Shared constants. Stored as plain strings (portable) and protected by CHECK constraints."""
from __future__ import annotations

ROLES = ("SUPER_ADMIN", "ADMIN", "VIEWER")
STATUSES = ("ACTIVE", "INACTIVE")
EMPLOYMENT = ("FULL_TIME", "PART_TIME", "CONTRACT", "VISITING")
AVAILABILITY = ("AVAILABLE", "PREFERRED", "UNAVAILABLE")
SEMESTERS = ("FIRST", "SECOND")
LEVELS = (100, 200, 300, 400, 500, 600)
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

ROOM_TYPES = ("STANDARD_CLASSROOM", "LECTURE_HALL", "COMPUTER_LABORATORY", "SCIENCE_LABORATORY", "SEMINAR_ROOM")
ROOM_TYPE_LABELS = {
    "STANDARD_CLASSROOM": "Standard classroom",
    "LECTURE_HALL": "Lecture hall",
    "COMPUTER_LABORATORY": "Computer laboratory",
    "SCIENCE_LABORATORY": "Science laboratory",
    "SEMINAR_ROOM": "Seminar room",
}
# required course room type -> room types able to host it
ROOM_COMPAT = {
    "STANDARD_CLASSROOM": ("STANDARD_CLASSROOM", "LECTURE_HALL", "SEMINAR_ROOM"),
    "LECTURE_HALL": ("LECTURE_HALL",),
    "COMPUTER_LABORATORY": ("COMPUTER_LABORATORY",),
    "SCIENCE_LABORATORY": ("SCIENCE_LABORATORY",),
    "SEMINAR_ROOM": ("SEMINAR_ROOM", "STANDARD_CLASSROOM"),
}

TT_DRAFT, TT_GENERATED, TT_VALIDATED, TT_APPROVED, TT_PUBLISHED, TT_ARCHIVED = (
    "DRAFT", "GENERATED", "VALIDATED", "APPROVED", "PUBLISHED", "ARCHIVED")
TIMETABLE_STATUSES = (TT_DRAFT, TT_GENERATED, TT_VALIDATED, TT_APPROVED, TT_PUBLISHED, TT_ARCHIVED)

GEN_STATUSES = ("RUNNING", "COMPLETED", "FAILED", "INTERRUPTED")


def in_list(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"
