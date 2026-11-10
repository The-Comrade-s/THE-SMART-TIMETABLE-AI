from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.enums import EMPLOYMENT
from database.models import CourseAssignment, Department, Lecturer
from services.common import ValidationError, clean, escape_like, get_or_404, integrity_guard, require_text
from validation.rules import validate_email


def _fields(session, staff_id, first_name, last_name, email, phone, department_id, employment_status):
    dep = session.get(Department, department_id)
    if dep is None:
        raise ValidationError("Select a department for the lecturer.")
    if dep.status != "ACTIVE":
        raise ValidationError("The selected department is inactive.")
    if employment_status not in EMPLOYMENT:
        raise ValidationError("Select a valid employment status.")
    phone = clean(phone)
    if phone and not all(c.isdigit() or c in "+- ()" for c in phone):
        raise ValidationError("Phone number contains invalid characters.")
    return dict(staff_id=require_text(staff_id, "Staff ID", 30).upper(),
                first_name=require_text(first_name, "First name", 80), last_name=require_text(last_name, "Last name", 80),
                email=validate_email(email), phone=phone or None, department_id=department_id,
                employment_status=employment_status)


def create_lecturer(session: Session, actor, staff_id, first_name, last_name, email, phone, department_id,
                    employment_status="FULL_TIME") -> Lecturer:
    require(actor, Permission.MANAGE_RECORDS)
    data = _fields(session, staff_id, first_name, last_name, email, phone, department_id, employment_status)
    _check_duplicates(session, data)
    lec = Lecturer(**data)
    with integrity_guard(session, "A lecturer with this staff ID or email already exists."):
        session.add(lec)
    return lec


def _check_duplicates(session, data, exclude_id=None):
    for col, label in ((Lecturer.staff_id, "staff ID"), (Lecturer.email, "email address")):
        q = select(Lecturer.id).where(col == data[col.key])
        if exclude_id:
            q = q.where(Lecturer.id != exclude_id)
        if session.scalar(q) is not None:
            raise ValidationError(f"A lecturer with this {label} already exists.")


def update_lecturer(session: Session, actor, lecturer_id: int, staff_id, first_name, last_name, email, phone,
                    department_id, employment_status) -> Lecturer:
    require(actor, Permission.MANAGE_RECORDS)
    lec = get_or_404(session, Lecturer, lecturer_id, "Lecturer")
    data = _fields(session, staff_id, first_name, last_name, email, phone, department_id, employment_status)
    _check_duplicates(session, data, lecturer_id)
    with integrity_guard(session, "A lecturer with this staff ID or email already exists."):
        for k, v in data.items():
            setattr(lec, k, v)
    return lec


def set_lecturer_status(session: Session, actor, lecturer_id: int, active: bool) -> Lecturer:
    require(actor, Permission.MANAGE_RECORDS)
    lec = get_or_404(session, Lecturer, lecturer_id, "Lecturer")
    lec.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return lec


def list_lecturers(session: Session, actor, search: str = "", department_id: Optional[int] = None,
                   status: Optional[str] = None) -> list[Lecturer]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(Lecturer).order_by(Lecturer.last_name, Lecturer.first_name)
    if search.strip():
        like = f"%{escape_like(search.strip().lower())}%"
        q = q.where(or_(*(func.lower(c).like(like, escape="\\") for c in
                          (Lecturer.first_name, Lecturer.last_name, Lecturer.staff_id, Lecturer.email))))
    if department_id:
        q = q.where(Lecturer.department_id == department_id)
    if status:
        q = q.where(Lecturer.status == status)
    return list(session.scalars(q))


def lecturer_profile(session: Session, actor, lecturer_id: int) -> dict:
    require(actor, Permission.VIEW_RECORDS)
    lec = get_or_404(session, Lecturer, lecturer_id, "Lecturer")
    assignments = list(session.scalars(select(CourseAssignment).where(CourseAssignment.lecturer_id == lecturer_id)
                                       .order_by(CourseAssignment.academic_session.desc())))
    return {"lecturer": lec, "department": lec.department, "assignments": assignments}
