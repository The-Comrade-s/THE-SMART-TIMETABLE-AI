"""Independent timetable validator.

Deliberately does NOT use the Genetic Algorithm's constraint code or fitness score. It reads the reference data
(assignments, rooms, availability, time slots) straight from the database and checks every candidate entry
with plain brute-force pairwise comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.enums import DAYS, ROOM_COMPAT
from database.models import (Classroom, CourseAssignment, LecturerAvailability, RoomAvailability, StudentGroup,
                             TimeSlot, Lecturer, Course)
from validation.rules import fmt_time, from_minutes, to_minutes

LECTURER, CLASSROOM, GROUP = "LECTURER_CONFLICT", "CLASSROOM_CONFLICT", "STUDENT_GROUP_CONFLICT"
AVAILABILITY, CAPACITY, ROOM_TYPE = "AVAILABILITY_CONFLICT", "CAPACITY_CONFLICT", "ROOM_TYPE_CONFLICT"
DURATION, WORKING_HOURS, MISSING, DUPLICATE = "DURATION_CONFLICT", "WORKING_HOURS_CONFLICT", "MISSING_SESSION", "DUPLICATE_SESSION"
CONFLICT_TYPES = (LECTURER, CLASSROOM, GROUP, AVAILABILITY, CAPACITY, ROOM_TYPE, DURATION, WORKING_HOURS, MISSING, DUPLICATE)
SEVERITY = {LECTURER: "CRITICAL", CLASSROOM: "CRITICAL", GROUP: "CRITICAL", AVAILABILITY: "HIGH", CAPACITY: "HIGH",
            ROOM_TYPE: "HIGH", WORKING_HOURS: "HIGH", MISSING: "HIGH", DUPLICATE: "HIGH", DURATION: "MEDIUM"}
TYPE_LABELS = {LECTURER: "Lecturer conflict", CLASSROOM: "Classroom conflict", GROUP: "Student group conflict",
               AVAILABILITY: "Availability conflict", CAPACITY: "Capacity conflict", ROOM_TYPE: "Room type conflict",
               DURATION: "Duration conflict", WORKING_HOURS: "Working-hours conflict", MISSING: "Missing session",
               DUPLICATE: "Duplicate session"}


@dataclass(frozen=True)
class EntryDraft:
    assignment_id: int
    session_no: int
    classroom_id: int
    day: int
    start: int   # minutes since midnight
    end: int
    entry_id: Optional[int] = None


@dataclass
class Conflict:
    type: str
    severity: str
    explanation: str
    course: str = ""
    lecturer: str = ""
    classroom: str = ""
    group: str = ""
    day: Optional[int] = None
    start: Optional[int] = None
    end: Optional[int] = None
    assignment_id: Optional[int] = None
    entry_ids: Tuple[int, ...] = ()

    def as_row(self) -> dict:
        d = asdict(self)
        d["day"] = DAYS[self.day] if self.day is not None else ""
        d["start"] = fmt_time(from_minutes(self.start)) if self.start is not None else ""
        d["end"] = fmt_time(from_minutes(self.end)) if self.end is not None else ""
        d["type_label"] = TYPE_LABELS[self.type]
        return d


def _merge(intervals: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _within(intervals: Sequence[Tuple[int, int]], s: int, e: int) -> bool:
    return any(a <= s and e <= b for a, b in intervals)


def _clashes(unavail: Sequence[Tuple[int, int]], s: int, e: int) -> bool:
    return any(s < b and a < e for a, b in unavail)


def validate_entries(session: Session, drafts: Sequence[EntryDraft], academic_session: str, semester: str,
                     department_id: Optional[int] = None, level: Optional[int] = None) -> List[Conflict]:
    conflicts: List[Conflict] = []

    # --- reference data ---------------------------------------------------------------------------
    q = (select(CourseAssignment).join(StudentGroup, StudentGroup.id == CourseAssignment.group_id)
         .where(CourseAssignment.academic_session == academic_session, CourseAssignment.semester == semester,
                CourseAssignment.status == "ACTIVE"))
    if department_id:
        q = q.where(StudentGroup.department_id == department_id)
    if level:
        q = q.where(StudentGroup.level == level)
    in_scope: Dict[int, CourseAssignment] = {
        a.id: a for a in session.scalars(q)
        if a.course.status == "ACTIVE" and a.lecturer.status == "ACTIVE" and a.group.status == "ACTIVE"}
    assignments: Dict[int, CourseAssignment] = dict(in_scope)
    for d in drafts:
        if d.assignment_id not in assignments:
            a = session.get(CourseAssignment, d.assignment_id)
            if a is not None:
                assignments[d.assignment_id] = a
    rooms: Dict[int, Classroom] = {r.id: r for r in session.scalars(select(Classroom))}
    slots = list(session.scalars(select(TimeSlot).where(TimeSlot.is_active.is_(True))))
    windows = {day: _merge((to_minutes(s.start_time), to_minutes(s.end_time)) for s in slots if s.day_of_week == day)
               for day in {s.day_of_week for s in slots}}
    lec_ids = {a.lecturer_id for a in assignments.values()}
    lec_pos: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    lec_neg: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for r in session.scalars(select(LecturerAvailability).where(LecturerAvailability.lecturer_id.in_(lec_ids or [0]))):
        target = lec_neg if r.status == "UNAVAILABLE" else lec_pos
        target.setdefault((r.lecturer_id, r.day_of_week), []).append((to_minutes(r.start_time), to_minutes(r.end_time)))
    room_pos: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    room_neg: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    rooms_with_pos = set()
    for r in session.scalars(select(RoomAvailability)):
        if r.status == "UNAVAILABLE":
            room_neg.setdefault((r.classroom_id, r.day_of_week), []).append((to_minutes(r.start_time), to_minutes(r.end_time)))
        else:
            rooms_with_pos.add(r.classroom_id)
            room_pos.setdefault((r.classroom_id, r.day_of_week), []).append((to_minutes(r.start_time), to_minutes(r.end_time)))

    expected: Dict[Tuple[int, int], int] = {}
    for aid, a in in_scope.items():
        from services.course_service import get_course_sessions   # local import avoids a cycle
        for no, dur in enumerate(get_course_sessions(a.course), start=1):
            expected[(aid, no)] = dur

    def ctx(d: EntryDraft, **kw) -> dict:
        a = assignments.get(d.assignment_id)
        room = rooms.get(d.classroom_id)
        base = dict(course=f"{a.course.code} - {a.course.title}" if a else "", lecturer=a.lecturer.full_name if a else "",
                    group=a.group.name if a else "", classroom=f"{room.building} {room.name}" if room else "",
                    day=d.day, start=d.start, end=d.end, assignment_id=d.assignment_id,
                    entry_ids=(d.entry_id,) if d.entry_id else ())
        base.update(kw)
        return base

    def add(ctype: str, text: str, d: EntryDraft, **kw) -> None:
        conflicts.append(Conflict(type=ctype, severity=SEVERITY[ctype], explanation=text, **ctx(d, **kw)))

    # --- per-entry checks -------------------------------------------------------------------------
    seen: Dict[Tuple[int, int], EntryDraft] = {}
    for d in drafts:
        a, room = assignments.get(d.assignment_id), rooms.get(d.classroom_id)
        key = (d.assignment_id, d.session_no)
        if key in seen:
            add(DUPLICATE, f"Session {d.session_no} of this course assignment is scheduled more than once.", d)
        seen[key] = d
        if a is None or room is None:
            add(AVAILABILITY, "The entry refers to a record that no longer exists.", d)
            continue
        want = expected.get(key)
        if want is None:
            add(DURATION, f"Session {d.session_no} is not part of this course's weekly pattern.", d)
        elif d.end - d.start != want:
            add(DURATION, f"Session length is {d.end - d.start} minutes but the course requires {want} minutes.", d)
        if room.capacity < a.group.population:
            add(CAPACITY, f"{room.name} seats {room.capacity} but the group has {a.group.population} students.", d)
        if room.room_type not in ROOM_COMPAT.get(a.course.required_room_type, (a.course.required_room_type,)):
            add(ROOM_TYPE, f"The course needs {a.course.required_room_type.replace('_', ' ').lower()} but {room.name} is "
                           f"a {room.room_type.replace('_', ' ').lower()}.", d)
        if not _within(windows.get(d.day, []), d.start, d.end):
            add(WORKING_HOURS, "The session falls outside the institution's permitted teaching hours.", d)
        lp = _merge(lec_pos.get((a.lecturer_id, d.day), []))
        if not _within(lp, d.start, d.end) or _clashes(lec_neg.get((a.lecturer_id, d.day), []), d.start, d.end):
            add(AVAILABILITY, f"{a.lecturer.full_name} is not available at this time.", d)
        if room.status != "ACTIVE" or not room.is_available:
            add(AVAILABILITY, f"{room.name} is inactive or marked unavailable.", d)
        elif (room.id in rooms_with_pos and not _within(_merge(room_pos.get((room.id, d.day), [])), d.start, d.end)) \
                or _clashes(room_neg.get((room.id, d.day), []), d.start, d.end):
            add(AVAILABILITY, f"{room.name} is not available at this time.", d)

    # --- pairwise overlap checks (partial overlaps included) --------------------------------------
    def lecturer_of(d): return assignments[d.assignment_id].lecturer_id if d.assignment_id in assignments else None
    def group_of(d): return assignments[d.assignment_id].group_id if d.assignment_id in assignments else None
    for ctype, owner_fn, noun in ((LECTURER, lecturer_of, "lecturer"), (CLASSROOM, lambda d: d.classroom_id, "classroom"),
                                  (GROUP, group_of, "student group")):
        for i in range(len(drafts)):
            for j in range(i + 1, len(drafts)):
                x, y = drafts[i], drafts[j]
                oi = owner_fn(x)
                if oi is None or oi != owner_fn(y) or x.day != y.day:
                    continue
                if x.start < y.end and y.start < x.end:
                    other = assignments.get(y.assignment_id)
                    add(ctype, f"The same {noun} is booked for two overlapping sessions"
                               f"{' (' + other.course.code + ')' if other else ''}.", x,
                        entry_ids=tuple(e for e in (x.entry_id, y.entry_id) if e))

    # --- completeness ------------------------------------------------------------------------------
    present = {(d.assignment_id, d.session_no) for d in drafts}
    for (aid, no), dur in sorted(expected.items()):
        if (aid, no) not in present:
            a = in_scope[aid]
            conflicts.append(Conflict(MISSING, SEVERITY[MISSING],
                                      f"Session {no} ({dur} minutes) of {a.course.code} for {a.group.name} is not scheduled.",
                                      course=f"{a.course.code} - {a.course.title}", lecturer=a.lecturer.full_name,
                                      group=a.group.name, assignment_id=aid))
    return conflicts


def summarise(conflicts: Sequence[Conflict]) -> dict:
    counts = {t: 0 for t in CONFLICT_TYPES}
    for c in conflicts:
        counts[c.type] += 1
    return {"total": len(conflicts), "by_type": counts, "hard_violations": len(conflicts)}
