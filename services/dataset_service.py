"""Dataset registry: import, listing, revalidation and removal of test datasets."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import (AlgorithmConfiguration, Classroom, Course, CourseAssignment, Dataset, DatasetMember, Department,
                             ExamDay, ExamEntry, ExamSession, GenerationHistory, Lecturer, StudentGroup, TimeSlot, Timetable,
                             TimetableAudit, TimetableEntry)
from importers.noun_exam_pdf import ExtractionResult
from importers.noun_import import DATASET_NAME, DRAFT_NOTICE, build_report, validation_status_for
from services.common import NotFoundError, ServiceError, ValidationError, utcnow

log = logging.getLogger(__name__)


@dataclass
class ImportOutcome:
    dataset_id: int
    status: str                 # IMPORTED | ALREADY_IMPORTED
    imported: int
    duplicates_prevented: int
    skipped_for_review: int
    report: dict


def import_extraction(session: Session, actor, result: ExtractionResult, include_review: bool = True,
                      name: str = DATASET_NAME) -> ImportOutcome:
    """Store an extraction. Existing data is never changed; importing the same document again adds nothing."""
    require(actor, Permission.IMPORT_DATASETS)
    if not result.entries:
        raise ValidationError("The extraction contains no records, so nothing can be imported.")
    existing = session.scalar(select(Dataset).where(Dataset.dataset_type == "EXAM_TIMETABLE_SOURCE",
                                                    Dataset.source_sha256 == result.source_sha256))
    if existing is not None:
        return ImportOutcome(existing.id, "ALREADY_IMPORTED", 0, len(result.entries), 0, existing.report or {})
    report = build_report(result)
    chosen = [e for e in result.entries if include_review or not e.needs_review]
    skipped = len(result.entries) - len(chosen)
    try:
        with session.begin_nested():
            ds = Dataset(name=name, dataset_type="EXAM_TIMETABLE_SOURCE", source_document=result.source_name,
                         source_sha256=result.source_sha256, is_draft_source=True, is_test_data=True, record_count=len(chosen),
                         import_status="IMPORTED", validation_status=validation_status_for(report), notes=DRAFT_NOTICE,
                         imported_by=getattr(actor, "id", None), validated_at=utcnow())
            session.add(ds)
            session.flush()
            session_ids = {}
            for d in result.days:
                group = result.group_for_day(d.day_no)
                row = ExamDay(dataset_id=ds.id, day_no=d.day_no, exam_date=d.exam_date, weekday=d.weekday, date_text=d.date_text,
                              page_no=d.page_no, faculty_group_code=group, faculty_group_text=(result.legend.get(group) or {}).get("text"),
                              review_notes=d.review or None)
                for s in d.sessions:
                    row.sessions.append(ExamSession(slot_no=s.slot, label_printed=s.label, start_time=s.start))
                session.add(row)
                session.flush()
                for s in row.sessions:
                    session_ids[(d.day_no, s.slot_no)] = s.id
            for e in chosen:
                sid = session_ids.get((e.day_no, e.slot))
                if sid is None:
                    raise ValidationError(f"Record {e.course_code or '(no code)'} on day {e.day_no} has no examination session.")
                session.add(ExamEntry(dataset_id=ds.id, session_id=sid, record_key=e.record_key(result.source_sha256), page_no=e.page_no,
                                      column_index=e.column_index, row_in_column=e.row_in_column, course_code=e.course_code,
                                      course_title=e.course_title, base_code=e.base_code, batch=e.batch, noun_prefixed=e.noun_prefixed,
                                      needs_review=e.needs_review, review_reasons=e.review_reasons or None,
                                      informational=e.informational or None))
            report.update(imported=len(chosen), duplicates_prevented=0, skipped_for_review=skipped)
            ds.report = report
            session.flush()
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("Dataset import failed")
        raise ServiceError("The import failed and nothing was saved. Existing data was not changed.") from exc
    return ImportOutcome(ds.id, "IMPORTED", len(chosen), 0, skipped, report)


def list_datasets(session: Session, actor) -> List[Dataset]:
    require(actor, Permission.IMPORT_DATASETS)
    return list(session.scalars(select(Dataset).order_by(Dataset.imported_at.desc(), Dataset.id.desc())))


def get_dataset(session: Session, actor, dataset_id: int) -> Dataset:
    require(actor, Permission.IMPORT_DATASETS)
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset was not found.")
    return ds


def revalidate_dataset(session: Session, actor, dataset_id: int) -> dict:
    """Re-check a stored dataset from the database (no PDF needed) and update its validation status."""
    ds = get_dataset(session, actor, dataset_id)
    checks: List[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    if ds.dataset_type == "EXAM_TIMETABLE_SOURCE":
        rep = ds.report or {}
        days = list(session.scalars(select(ExamDay).where(ExamDay.dataset_id == ds.id).order_by(ExamDay.day_no)))
        n_sessions = session.scalar(select(func.count(ExamSession.id)).join(ExamDay).where(ExamDay.dataset_id == ds.id)) or 0
        rows = list(session.scalars(select(ExamEntry).where(ExamEntry.dataset_id == ds.id)))
        check("Examination days present", [d.day_no for d in days] == list(range(1, 17)), f"{len(days)} of 16 days")
        check("Three sessions per day", n_sessions == 3 * len(days), f"{n_sessions} sessions")
        check("Every day has a date matching its weekday", all(d.exam_date and d.exam_date.strftime("%A") == d.weekday for d in days))
        check("Record count equals the stored count", len(rows) == ds.record_count, f"{len(rows)} stored, {ds.record_count} expected")
        if rep.get("imported") is not None:
            check("Record count equals the imported count in the report", len(rows) == rep["imported"])
        check("Every record has a course code", all(r.course_code for r in rows))
        check("Every record has a course title", all(r.course_title for r in rows))
        check("Record keys are unique", len({r.record_key for r in rows}) == len(rows))
        check("Batch records match their code suffix", all((r.batch is None) == (not r.course_code.endswith(("-A", "-B"))) for r in rows))
        check("NOUN-prefixed records keep their prefix", all(r.noun_prefixed == r.course_code.startswith("NOUN-") for r in rows))
        check("Source page recorded for every record", all(1 <= r.page_no <= 8 for r in rows))
        check("Original extraction covered all pages and days", bool(rep.get("coverage_ok")))
        flagged = sum(r.needs_review for r in rows)
        status = "INVALID" if any(not c["passed"] for c in checks) else ("NEEDS_REVIEW" if flagged else "VALID")
        summary = {"records": len(rows), "flagged_for_review": flagged}
    else:
        members = Counter(m.entity for m in session.scalars(select(DatasetMember).where(DatasetMember.dataset_id == ds.id)))
        check("Synthetic records exist", sum(members.values()) > 0, f"{sum(members.values())} records")
        check("Courses, lecturers, rooms, groups and assignments exist",
              all(members.get(k, 0) > 0 for k in ("course", "lecturer", "classroom", "student_group", "course_assignment")))
        status = "INVALID" if any(not c["passed"] for c in checks) else "VALID"
        summary = dict(members)
    ds.validation_status, ds.validated_at = status, utcnow()
    ds.report = {**(ds.report or {}), "revalidation": {"checks": checks, "summary": summary, "status": status}}
    session.flush()
    return ds.report["revalidation"]


# ---------------------------------------------------------------------------------------------- removal
def _members(session: Session, dataset_id: int, entity: str) -> List[int]:
    return list(session.scalars(select(DatasetMember.entity_id).where(DatasetMember.dataset_id == dataset_id,
                                                                      DatasetMember.entity == entity)))


def remove_dataset(session: Session, actor, dataset_id: int) -> dict:
    """Remove a TEST dataset and only the records it created. Real records are never touched."""
    require(actor, Permission.REMOVE_DATASETS)
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset was not found.")
    if not ds.is_test_data:
        raise ValidationError("Only datasets marked as test data can be removed.")
    children = session.scalar(select(func.count(Dataset.id)).where(Dataset.parent_dataset_id == ds.id)) or 0
    if children:
        raise ValidationError("Remove the synthetic lecture dataset built from this dataset first.")
    removed: dict = {}
    try:
        with session.begin_nested():
            if ds.dataset_type == "SYNTHETIC_LECTURE_TEST":
                removed = _remove_synthetic(session, ds)
            else:
                removed = {"exam_entries": session.scalar(select(func.count(ExamEntry.id)).where(ExamEntry.dataset_id == ds.id)) or 0}
            session.execute(delete(DatasetMember).where(DatasetMember.dataset_id == ds.id))
            session.execute(delete(ExamEntry).where(ExamEntry.dataset_id == ds.id))
            session.execute(delete(ExamSession).where(ExamSession.day_id.in_(select(ExamDay.id).where(ExamDay.dataset_id == ds.id))))
            session.execute(delete(ExamDay).where(ExamDay.dataset_id == ds.id))
            session.delete(ds)
            session.flush()
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("Dataset removal failed")
        raise ServiceError("The dataset could not be removed. Nothing was deleted.") from exc
    return removed


def _remove_synthetic(session: Session, ds: Dataset) -> dict:
    ids = {k: _members(session, ds.id, k) for k in ("department", "lecturer", "classroom", "student_group", "course",
                                                    "course_assignment", "time_slot", "timetable")}
    assignments = set(ids["course_assignment"])
    # every timetable that schedules a synthetic assignment is test output, wherever it was generated
    tt_ids = set(ids["timetable"]) | set(session.scalars(select(TimetableEntry.timetable_id).where(
        TimetableEntry.course_assignment_id.in_(assignments or [0]))))
    tts = list(session.scalars(select(Timetable).where(Timetable.id.in_(tt_ids or [0]))))
    protected = [t for t in tts if t.status in ("APPROVED", "PUBLISHED")]
    if protected:
        raise ValidationError("A timetable generated from this test data is approved or published. Archive it before removing the dataset.")
    foreign = session.scalar(select(func.count(TimetableEntry.id)).where(
        TimetableEntry.timetable_id.in_(tt_ids or [0]), TimetableEntry.course_assignment_id.notin_(assignments or [0])))
    if foreign:
        raise ValidationError("A timetable generated from this test data also contains records from other sources, so it was kept.")
    room_ids = set(ids["classroom"])
    other_rooms = session.scalar(select(func.count(TimetableEntry.id)).where(
        TimetableEntry.classroom_id.in_(room_ids or [0]), TimetableEntry.timetable_id.notin_(tt_ids or [0])))
    if other_rooms:
        raise ValidationError("A synthetic classroom is used by a timetable that is not part of this dataset.")
    ordered = sorted(tt_ids, reverse=True)           # revisions (higher ids) before their parents
    session.execute(delete(TimetableAudit).where(TimetableAudit.timetable_id.in_(tt_ids or [0])))
    session.execute(delete(GenerationHistory).where(GenerationHistory.timetable_id.in_(tt_ids or [0])))
    session.execute(delete(TimetableEntry).where(TimetableEntry.timetable_id.in_(tt_ids or [0])))
    for tid in ordered:
        t = session.get(Timetable, tid)
        if t is not None:
            session.delete(t)
            session.flush()
    session.execute(delete(CourseAssignment).where(CourseAssignment.id.in_(assignments or [0])))
    session.execute(delete(StudentGroup).where(StudentGroup.id.in_(ids["student_group"] or [0])))
    session.execute(delete(Course).where(Course.id.in_(ids["course"] or [0])))          # sessions cascade
    session.execute(delete(Lecturer).where(Lecturer.id.in_(ids["lecturer"] or [0])))    # availability cascades
    session.execute(delete(Classroom).where(Classroom.id.in_(ids["classroom"] or [0])))  # availability cascades
    session.execute(delete(TimeSlot).where(TimeSlot.id.in_(ids["time_slot"] or [0])))
    session.execute(delete(Department).where(Department.id.in_(ids["department"] or [0])))
    session.flush()
    return {"timetables": len(tt_ids), **{k: len(v) for k, v in ids.items() if k != "timetable"}}
