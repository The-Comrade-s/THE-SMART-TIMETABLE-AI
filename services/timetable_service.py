"""Timetable queries, lifecycle (validate / approve / publish / archive / revise) and audit trail."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, PermissionDenied, has_permission, require
from database.models import Timetable, TimetableAudit, TimetableEntry
from services.common import utcnow, ConflictError, NotFoundError, ValidationError, escape_like
from services.generation_service import entries_to_drafts, next_version
from validation.timetable_validator import Conflict, summarise, validate_entries

TRANSITIONS = {
    "DRAFT": {"GENERATED", "ARCHIVED"},
    "GENERATED": {"VALIDATED", "ARCHIVED"},
    "VALIDATED": {"GENERATED", "APPROVED", "ARCHIVED"},
    "APPROVED": {"PUBLISHED", "ARCHIVED"},
    "PUBLISHED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


def _audit(session: Session, tt: Timetable, action: str, actor, details: str = "") -> None:
    session.add(TimetableAudit(timetable_id=tt.id, action=action, actor_id=getattr(actor, "id", None), details=details or None))


def can_view(actor, tt: Timetable) -> bool:
    if has_permission(actor, Permission.VIEW_ALL_TIMETABLES):
        return True
    return has_permission(actor, Permission.VIEW_PUBLISHED) and tt.status == "PUBLISHED"


def get_timetable(session: Session, actor, timetable_id: int) -> Timetable:
    tt = session.get(Timetable, timetable_id)
    if tt is None:
        raise NotFoundError("Timetable was not found.")
    if not can_view(actor, tt):
        raise PermissionDenied("You do not have permission to view this timetable.")
    return tt


def list_timetables(session: Session, actor, search: str = "", academic_session: Optional[str] = None,
                    semester: Optional[str] = None, department_id: Optional[int] = None, status: Optional[str] = None,
                    level: Optional[int] = None) -> List[Timetable]:
    if not (has_permission(actor, Permission.VIEW_ALL_TIMETABLES) or has_permission(actor, Permission.VIEW_PUBLISHED)):
        raise PermissionDenied("You do not have permission to view timetables.")
    q = select(Timetable).order_by(Timetable.generated_at.desc(), Timetable.id.desc())
    if not has_permission(actor, Permission.VIEW_ALL_TIMETABLES):
        q = q.where(Timetable.status == "PUBLISHED")
    if search.strip():
        q = q.where(Timetable.name.ilike(f"%{escape_like(search.strip())}%", escape="\\"))
    for col, val in ((Timetable.academic_session, academic_session), (Timetable.semester, semester),
                     (Timetable.department_id, department_id), (Timetable.status, status), (Timetable.level, level)):
        if val:
            q = q.where(col == val)
    return list(session.scalars(q))


def versions_of(session: Session, actor, timetable_id: int) -> List[Timetable]:
    tt = get_timetable(session, actor, timetable_id)
    q = select(Timetable).where(Timetable.academic_session == tt.academic_session, Timetable.semester == tt.semester,
                                Timetable.department_id == tt.department_id if tt.department_id else Timetable.department_id.is_(None),
                                Timetable.level == tt.level if tt.level else Timetable.level.is_(None)).order_by(Timetable.version)
    return [t for t in session.scalars(q) if can_view(actor, t)]


def audit_trail(session: Session, actor, timetable_id: int) -> List[TimetableAudit]:
    require(actor, Permission.VIEW_HISTORY)
    return list(session.scalars(select(TimetableAudit).where(TimetableAudit.timetable_id == timetable_id)
                                .order_by(TimetableAudit.created_at, TimetableAudit.id)))


def detect_conflicts(session: Session, actor, timetable_id: int) -> List[Conflict]:
    tt = get_timetable(session, actor, timetable_id)
    return validate_entries(session, entries_to_drafts(tt.entries), tt.academic_session, tt.semester, tt.department_id, tt.level)


def _transition(tt: Timetable, new: str) -> None:
    if new not in TRANSITIONS[tt.status]:
        raise ValidationError(f"A {tt.status.lower()} timetable cannot become {new.lower()}.")
    tt.status = new


def revalidate(session: Session, actor, timetable_id: int) -> List[Conflict]:
    """Re-run the independent validator and store the result. Never labels an invalid timetable as valid."""
    require(actor, Permission.GENERATE)
    tt = get_timetable(session, actor, timetable_id)
    conflicts = detect_conflicts(session, actor, timetable_id)
    summary = summarise(conflicts)
    tt.hard_violations, tt.is_valid = summary["total"], summary["total"] == 0
    tt.validation_summary = {**(tt.validation_summary or {}), "independent": summary}
    if tt.status in ("GENERATED", "VALIDATED"):
        tt.status = "VALIDATED" if tt.is_valid else "GENERATED"
    _audit(session, tt, "VALIDATED" if tt.is_valid else "VALIDATION_FAILED", actor, f"{summary['total']} hard violations")
    session.flush()
    return conflicts


def approve(session: Session, actor, timetable_id: int) -> Timetable:
    require(actor, Permission.APPROVE)
    tt = get_timetable(session, actor, timetable_id)
    conflicts = detect_conflicts(session, actor, timetable_id)
    if conflicts:
        tt.is_valid, tt.hard_violations = False, len(conflicts)
        session.flush()
        raise ValidationError(f"An invalid timetable cannot be approved. Independent validation found {len(conflicts)} hard constraint violations.")
    if tt.status != "VALIDATED":
        raise ValidationError("Only a validated timetable can be approved.")
    _transition(tt, "APPROVED")
    tt.approved_by, tt.approved_at, tt.is_valid, tt.hard_violations = actor.id, utcnow(), True, 0
    _audit(session, tt, "APPROVED", actor)
    session.flush()
    return tt


def publish(session: Session, actor, timetable_id: int, replace_published: bool = False) -> Timetable:
    require(actor, Permission.PUBLISH)
    tt = get_timetable(session, actor, timetable_id)
    if tt.status != "APPROVED":
        raise ValidationError("Only an approved timetable can be published.")
    rivals = [t for t in session.scalars(select(Timetable).where(
        Timetable.academic_session == tt.academic_session, Timetable.semester == tt.semester, Timetable.status == "PUBLISHED",
        Timetable.id != tt.id)) if t.department_id == tt.department_id and t.level == tt.level]
    if rivals and not replace_published:
        raise ConflictError("A published timetable already exists for this scope. Confirm the replacement to publish this "
                            "version. The previous version will be archived, not deleted.")
    for old in rivals:
        old.status = "ARCHIVED"
        _audit(session, old, "ARCHIVED", actor, f"Replaced by version {tt.version} (timetable {tt.id})")
    _transition(tt, "PUBLISHED")
    tt.published_by, tt.published_at = actor.id, utcnow()
    _audit(session, tt, "PUBLISHED", actor)
    session.flush()
    return tt


def archive(session: Session, actor, timetable_id: int) -> Timetable:
    require(actor, Permission.APPROVE)
    tt = get_timetable(session, actor, timetable_id)
    _transition(tt, "ARCHIVED")
    _audit(session, tt, "ARCHIVED", actor)
    session.flush()
    return tt


def create_revision(session: Session, actor, timetable_id: int) -> Timetable:
    """Copy a timetable into a new GENERATED version (history is never overwritten)."""
    require(actor, Permission.GENERATE)
    src = get_timetable(session, actor, timetable_id)
    version = next_version(session, src.academic_session, src.semester, src.department_id, src.level)
    new = Timetable(name=f"{src.name.rsplit(' v', 1)[0]} v{version}", academic_session=src.academic_session,
                    semester=src.semester, department_id=src.department_id, level=src.level, version=version,
                    parent_id=src.id, status="GENERATED", fitness_score=src.fitness_score,
                    generation_number=src.generation_number, hard_violations=src.hard_violations,
                    soft_penalty=src.soft_penalty, is_valid=False, created_by=actor.id)
    session.add(new)
    session.flush()
    for e in src.entries:
        session.add(TimetableEntry(timetable_id=new.id, course_assignment_id=e.course_assignment_id, session_no=e.session_no,
                                   classroom_id=e.classroom_id, day_of_week=e.day_of_week, start_time=e.start_time,
                                   end_time=e.end_time, generation_metadata={"copied_from": src.id}))
    _audit(session, new, "REVISION_CREATED", actor, f"Copied from timetable {src.id} (version {src.version})")
    session.flush()
    return new
