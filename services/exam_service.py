"""Read access to imported examination timetables, plus parallel-session and student-group conflict analysis."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time
from typing import Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import (Course, CourseAssignment, Dataset, DatasetMember, ExamDay, ExamEntry, ExamSession, StudentGroup)
from services.common import NotFoundError, ValidationError, escape_like


@dataclass(frozen=True)
class ExamRow:
    entry_id: int
    day_no: int
    exam_date: Optional[date]
    weekday: str
    slot_no: int
    session_label: str
    session_start: time
    course_code: str
    course_title: str
    base_code: str
    batch: Optional[str]
    noun_prefixed: bool
    page_no: int
    faculty_group_code: Optional[str]
    needs_review: bool
    review_reasons: tuple
    informational: tuple

    @property
    def session_key(self) -> tuple:
        return (self.day_no, self.slot_no)


def _exam_dataset(session: Session, actor, dataset_id: int) -> Dataset:
    require(actor, Permission.IMPORT_DATASETS)
    ds = session.get(Dataset, dataset_id)
    if ds is None or ds.dataset_type != "EXAM_TIMETABLE_SOURCE":
        raise NotFoundError("Examination dataset was not found.")
    return ds


def search_entries(session: Session, actor, dataset_id: int, text: str = "", day_no: Optional[int] = None,
                   batch: Optional[str] = None, session_start: Optional[time] = None, noun_prefixed: Optional[bool] = None,
                   needs_review: Optional[bool] = None, faculty_group: Optional[str] = None, slot_no: Optional[int] = None,
                   exam_date: Optional[date] = None) -> List[ExamRow]:
    _exam_dataset(session, actor, dataset_id)
    q = (select(ExamEntry, ExamSession, ExamDay).join(ExamSession, ExamSession.id == ExamEntry.session_id)
         .join(ExamDay, ExamDay.id == ExamSession.day_id).where(ExamEntry.dataset_id == dataset_id)
         .order_by(ExamDay.day_no, ExamSession.slot_no, ExamEntry.column_index, ExamEntry.row_in_column))
    if text.strip():
        like = f"%{escape_like(text.strip().lower())}%"
        q = q.where(or_(func.lower(ExamEntry.course_code).like(like, escape="\\"),
                        func.lower(ExamEntry.course_title).like(like, escape="\\")))
    if day_no:
        q = q.where(ExamDay.day_no == day_no)
    if exam_date:
        q = q.where(ExamDay.exam_date == exam_date)
    if batch == "NONE":
        q = q.where(ExamEntry.batch.is_(None))
    elif batch:
        q = q.where(ExamEntry.batch == batch)
    if session_start:
        q = q.where(ExamSession.start_time == session_start)
    if slot_no:
        q = q.where(ExamSession.slot_no == slot_no)
    if noun_prefixed is not None:
        q = q.where(ExamEntry.noun_prefixed.is_(noun_prefixed))
    if needs_review is not None:
        q = q.where(ExamEntry.needs_review.is_(needs_review))
    if faculty_group:
        q = q.where(ExamDay.faculty_group_code == faculty_group)
    return [ExamRow(e.id, d.day_no, d.exam_date, d.weekday, s.slot_no, s.label_printed, s.start_time, e.course_code, e.course_title,
                    e.base_code, e.batch, e.noun_prefixed, e.page_no, d.faculty_group_code, e.needs_review,
                    tuple(e.review_reasons or ()), tuple(e.informational or ())) for e, s, d in session.execute(q)]


def get_entry(session: Session, actor, dataset_id: int, entry_id: int) -> ExamRow:
    rows = [r for r in search_entries(session, actor, dataset_id) if r.entry_id == entry_id]
    if not rows:
        raise NotFoundError("Examination record was not found.")
    return rows[0]


def list_days(session: Session, actor, dataset_id: int) -> List[ExamDay]:
    _exam_dataset(session, actor, dataset_id)
    return list(session.scalars(select(ExamDay).where(ExamDay.dataset_id == dataset_id).order_by(ExamDay.day_no)))


def session_times(session: Session, actor, dataset_id: int) -> List[time]:
    _exam_dataset(session, actor, dataset_id)
    return sorted(set(session.scalars(select(ExamSession.start_time).join(ExamDay).where(ExamDay.dataset_id == dataset_id))))


def parallel_summary(session: Session, actor, dataset_id: int) -> List[dict]:
    """Examinations held at the same time are normal (different student populations). This only counts them."""
    rows = search_entries(session, actor, dataset_id)
    by: Dict[tuple, List[ExamRow]] = defaultdict(list)
    for r in rows:
        by[r.session_key].append(r)
    return [{"day_no": k[0], "date": v[0].exam_date, "weekday": v[0].weekday, "slot": k[1], "time": v[0].session_label,
             "parallel_examinations": len(v), "conflict": False} for k, v in sorted(by.items())]


# --------------------------------------------------------------------------- student-group conflict detection
def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def detect_group_conflicts(session: Session, actor, exam_dataset_id: int, synthetic_dataset_id: int,
                           assumed_duration_minutes: Optional[int] = None) -> dict:
    """A genuine conflict exists only when ONE student group is registered for two overlapping examinations.

    Student groups come from the synthetic dataset (the PDF contains no populations). Without an assumed duration, two
    examinations overlap when they are in the same printed session; with one, intervals [start, start + duration) are compared.
    """
    _exam_dataset(session, actor, exam_dataset_id)
    syn = session.get(Dataset, synthetic_dataset_id)
    if syn is None or syn.dataset_type != "SYNTHETIC_LECTURE_TEST" or syn.parent_dataset_id != exam_dataset_id:
        raise ValidationError("The synthetic dataset does not belong to this examination dataset.")
    if assumed_duration_minutes is not None and not 15 <= assumed_duration_minutes <= 600:
        raise ValidationError("The assumed examination duration must be between 15 and 600 minutes.")
    rows = {r.entry_id: r for r in search_entries(session, actor, exam_dataset_id)}
    course_to_entry: Dict[int, int] = {}
    for m in session.scalars(select(DatasetMember).where(DatasetMember.dataset_id == synthetic_dataset_id, DatasetMember.entity == "course")):
        if m.note and m.note.startswith("source_exam_entry:"):
            course_to_entry[m.entity_id] = int(m.note.split(":", 1)[1])
    assigns = list(session.scalars(select(CourseAssignment).where(CourseAssignment.course_id.in_(course_to_entry or [0]))))
    by_group: Dict[int, List[ExamRow]] = defaultdict(list)
    for a in assigns:
        row = rows.get(course_to_entry.get(a.course_id, -1))
        if row is not None:
            by_group[a.group_id].append(row)
    names = {g.id: g.name for g in session.scalars(select(StudentGroup).where(StudentGroup.id.in_(list(by_group) or [0])))}
    conflicts = []
    for gid, items in by_group.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                x, y = items[i], items[j]
                if x.day_no != y.day_no:
                    continue
                if assumed_duration_minutes is None:
                    overlap = x.slot_no == y.slot_no
                else:
                    sx, sy = _minutes(x.session_start), _minutes(y.session_start)
                    overlap = sx < sy + assumed_duration_minutes and sy < sx + assumed_duration_minutes
                if overlap:
                    conflicts.append({"group": names.get(gid, str(gid)), "day_no": x.day_no, "date": x.exam_date,
                                      "course_a": x.course_code, "title_a": x.course_title, "time_a": x.session_label,
                                      "course_b": y.course_code, "title_b": y.course_title, "time_b": y.session_label,
                                      "explanation": "The same student group is registered for two overlapping examinations."})
    parallel_total = sum(1 for p in parallel_summary(session, actor, exam_dataset_id) if p["parallel_examinations"] > 1)
    return {"groups_checked": len(by_group), "courses_checked": sum(len(v) for v in by_group.values()), "conflicts": conflicts,
            "parallel_sessions": parallel_total,
            "method": ("same printed session" if assumed_duration_minutes is None
                       else f"intervals with an assumed duration of {assumed_duration_minutes} minutes")}
