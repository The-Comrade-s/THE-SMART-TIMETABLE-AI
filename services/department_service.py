from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import Course, Department, Lecturer, StudentGroup
from services.common import (ValidationError, escape_like, get_or_404, integrity_guard, require_text, clean)


def _fields(name, code, faculty, description):
    code = require_text(code, "Department code", 20).upper().replace(" ", "")
    return dict(name=require_text(name, "Department name", 150), code=code, faculty=clean(faculty) or None,
                description=clean(description) or None)


def create_department(session: Session, actor, name, code, faculty="", description="") -> Department:
    require(actor, Permission.MANAGE_DEPARTMENTS)
    dep = Department(**_fields(name, code, faculty, description))
    with integrity_guard(session, f"Department code {dep.code} is already in use."):
        session.add(dep)
    return dep


def update_department(session: Session, actor, dep_id: int, name, code, faculty="", description="") -> Department:
    require(actor, Permission.MANAGE_DEPARTMENTS)
    dep = get_or_404(session, Department, dep_id, "Department")
    data = _fields(name, code, faculty, description)
    with integrity_guard(session, f"Department code {data['code']} is already in use."):
        for k, v in data.items():
            setattr(dep, k, v)
    return dep


def set_department_status(session: Session, actor, dep_id: int, active: bool) -> Department:
    require(actor, Permission.MANAGE_DEPARTMENTS)
    dep = get_or_404(session, Department, dep_id, "Department")
    dep.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return dep


def delete_department(session: Session, actor, dep_id: int) -> None:
    """Hard delete is only allowed when nothing references the department."""
    require(actor, Permission.MANAGE_DEPARTMENTS)
    dep = get_or_404(session, Department, dep_id, "Department")
    refs = sum(session.scalar(select(func.count()).select_from(m).where(m.department_id == dep_id)) or 0
               for m in (Lecturer, Course, StudentGroup))
    if refs:
        raise ValidationError("This department has lecturers, courses or student groups. Deactivate it instead.")
    session.delete(dep)
    session.flush()


def list_departments(session: Session, actor, search: str = "", status: Optional[str] = None,
                     faculty: Optional[str] = None) -> list[Department]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(Department).order_by(Department.name)
    if search.strip():
        like = f"%{escape_like(search.strip().lower())}%"
        q = q.where(or_(func.lower(Department.name).like(like, escape="\\"),
                        func.lower(Department.code).like(like, escape="\\")))
    if status:
        q = q.where(Department.status == status)
    if faculty:
        q = q.where(Department.faculty == faculty)
    return list(session.scalars(q))


def list_faculties(session: Session, actor) -> list[str]:
    require(actor, Permission.VIEW_RECORDS)
    return [f for f in session.scalars(select(Department.faculty).where(Department.faculty.is_not(None)).distinct()
                                       .order_by(Department.faculty))]


def department_detail(session: Session, actor, dep_id: int) -> dict:
    require(actor, Permission.VIEW_RECORDS)
    dep = get_or_404(session, Department, dep_id, "Department")
    lecturers = list(session.scalars(select(Lecturer).where(Lecturer.department_id == dep_id).order_by(Lecturer.last_name)))
    courses = list(session.scalars(select(Course).where(Course.department_id == dep_id).order_by(Course.code)))
    return {"department": dep, "lecturers": lecturers, "courses": courses}
