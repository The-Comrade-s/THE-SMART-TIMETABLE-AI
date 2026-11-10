from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import CourseAssignment, Department, StudentGroup
from services.common import ValidationError, escape_like, get_or_404, integrity_guard, require_text
from validation.rules import validate_academic_session, validate_level, validate_positive_int


def _fields(session, name, department_id, level, programme, population, academic_session):
    dep = session.get(Department, department_id)
    if dep is None:
        raise ValidationError("A student group must belong to a department.")
    if dep.status != "ACTIVE":
        raise ValidationError("The selected department is inactive.")
    return dict(name=require_text(name, "Group name", 120), department_id=department_id, level=validate_level(level),
                programme=require_text(programme, "Programme", 150),
                population=validate_positive_int(population, "Student population", 20000),
                academic_session=validate_academic_session(academic_session))


def _dup(session, data, exclude_id=None):
    q = select(StudentGroup.id).where(func.lower(StudentGroup.name) == data["name"].lower(),
                                      StudentGroup.academic_session == data["academic_session"])
    if exclude_id:
        q = q.where(StudentGroup.id != exclude_id)
    if session.scalar(q) is not None:
        raise ValidationError("A group with this name already exists for the academic session.")


def create_group(session: Session, actor, name, department_id, level, programme, population, academic_session) -> StudentGroup:
    require(actor, Permission.MANAGE_RECORDS)
    data = _fields(session, name, department_id, level, programme, population, academic_session)
    _dup(session, data)
    grp = StudentGroup(**data)
    with integrity_guard(session, "A group with this name already exists for the academic session."):
        session.add(grp)
    return grp


def update_group(session: Session, actor, group_id: int, name, department_id, level, programme, population,
                 academic_session) -> StudentGroup:
    require(actor, Permission.MANAGE_RECORDS)
    grp = get_or_404(session, StudentGroup, group_id, "Student group")
    data = _fields(session, name, department_id, level, programme, population, academic_session)
    _dup(session, data, group_id)
    with integrity_guard(session, "A group with this name already exists for the academic session."):
        for k, v in data.items():
            setattr(grp, k, v)
    return grp


def set_group_status(session: Session, actor, group_id: int, active: bool) -> StudentGroup:
    require(actor, Permission.MANAGE_RECORDS)
    grp = get_or_404(session, StudentGroup, group_id, "Student group")
    grp.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return grp


def list_groups(session: Session, actor, search: str = "", department_id: Optional[int] = None,
                level: Optional[int] = None, academic_session: Optional[str] = None,
                status: Optional[str] = None) -> list[StudentGroup]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(StudentGroup).order_by(StudentGroup.name)
    if search.strip():
        like = f"%{escape_like(search.strip().lower())}%"
        q = q.where(or_(func.lower(StudentGroup.name).like(like, escape="\\"),
                        func.lower(StudentGroup.programme).like(like, escape="\\")))
    for col, val in ((StudentGroup.department_id, department_id), (StudentGroup.level, level),
                     (StudentGroup.academic_session, academic_session), (StudentGroup.status, status)):
        if val:
            q = q.where(col == val)
    return list(session.scalars(q))


def group_courses(session: Session, actor, group_id: int) -> list[CourseAssignment]:
    require(actor, Permission.VIEW_RECORDS)
    return list(session.scalars(select(CourseAssignment).where(CourseAssignment.group_id == group_id)))
