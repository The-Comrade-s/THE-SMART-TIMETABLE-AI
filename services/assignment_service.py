from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import Course, CourseAssignment, Lecturer, StudentGroup, TimetableEntry
from services.common import ValidationError, get_or_404, integrity_guard
from validation.rules import validate_academic_session, validate_semester


def create_assignment(session: Session, actor, course_id, lecturer_id, group_id, academic_session, semester) -> CourseAssignment:
    require(actor, Permission.MANAGE_RECORDS)
    course, lec, grp = session.get(Course, course_id), session.get(Lecturer, lecturer_id), session.get(StudentGroup, group_id)
    if course is None:
        raise ValidationError("Select a course.")
    if lec is None:
        raise ValidationError("Select a lecturer.")
    if grp is None:
        raise ValidationError("Select a student group.")
    for obj, label in ((course, "course"), (lec, "lecturer"), (grp, "student group")):
        if obj.status != "ACTIVE":
            raise ValidationError(f"The selected {label} is inactive.")
    academic_session, semester = validate_academic_session(academic_session), validate_semester(semester)
    if course.semester != semester:
        raise ValidationError(f"{course.code} is a {course.semester.lower()} semester course.")
    if grp.level != course.level:
        raise ValidationError(f"Course level {course.level} does not match group level {grp.level}.")
    if grp.academic_session != academic_session:
        raise ValidationError(f"The group belongs to session {grp.academic_session}, not {academic_session}.")
    exists = session.scalar(select(CourseAssignment.id).where(
        CourseAssignment.course_id == course_id, CourseAssignment.lecturer_id == lecturer_id,
        CourseAssignment.group_id == group_id, CourseAssignment.academic_session == academic_session,
        CourseAssignment.semester == semester))
    if exists:
        raise ValidationError("This assignment already exists for the selected session and semester.")
    a = CourseAssignment(course_id=course_id, lecturer_id=lecturer_id, group_id=group_id,
                         academic_session=academic_session, semester=semester)
    with integrity_guard(session, "This assignment already exists for the selected session and semester."):
        session.add(a)
    return a


def set_assignment_status(session: Session, actor, assignment_id: int, active: bool) -> CourseAssignment:
    require(actor, Permission.MANAGE_RECORDS)
    a = get_or_404(session, CourseAssignment, assignment_id, "Assignment")
    a.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return a


def delete_assignment(session: Session, actor, assignment_id: int) -> None:
    require(actor, Permission.MANAGE_RECORDS)
    a = get_or_404(session, CourseAssignment, assignment_id, "Assignment")
    if (session.scalar(select(func.count(TimetableEntry.id)).where(TimetableEntry.course_assignment_id == a.id)) or 0):
        raise ValidationError("This assignment appears in generated timetables. Deactivate it instead.")
    session.delete(a)
    session.flush()


def list_assignments(session: Session, actor, academic_session: Optional[str] = None, semester: Optional[str] = None,
                     course_id: Optional[int] = None, lecturer_id: Optional[int] = None,
                     group_id: Optional[int] = None) -> list[CourseAssignment]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(CourseAssignment).order_by(CourseAssignment.academic_session.desc(), CourseAssignment.id)
    for col, val in ((CourseAssignment.academic_session, academic_session), (CourseAssignment.semester, semester),
                     (CourseAssignment.course_id, course_id), (CourseAssignment.lecturer_id, lecturer_id),
                     (CourseAssignment.group_id, group_id)):
        if val:
            q = q.where(col == val)
    return list(session.scalars(q))
