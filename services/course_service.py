from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import Course, CourseAssignment, CourseSession, Department, TimetableEntry
from services.common import ValidationError, escape_like, get_or_404, integrity_guard, require_text
from validation.rules import validate_level, validate_positive_int, validate_room_type, validate_semester


def default_session_pattern(weekly_minutes: int) -> list[int]:
    """Blocks of up to two hours: 180 -> [120, 60]; 240 -> [120, 120]; 60 -> [60]."""
    blocks, remaining = [], weekly_minutes
    while remaining > 0:
        step = min(120, remaining)
        blocks.append(step)
        remaining -= step
    return blocks


def _validate_sessions(sessions: Sequence[int], weekly_minutes: int) -> list[int]:
    out = [validate_positive_int(s, "Session duration (minutes)", 480) for s in sessions]
    if not out:
        raise ValidationError("A course needs at least one weekly session.")
    if sum(out) != weekly_minutes:
        raise ValidationError(f"Session durations add up to {sum(out)} minutes but the weekly lecture "
                              f"duration is {weekly_minutes} minutes.")
    return out


def _fields(session, code, title, credit_units, department_id, level, semester, weekly_minutes, room_type):
    dep = session.get(Department, department_id)
    if dep is None:
        raise ValidationError("Select a department for the course.")
    if dep.status != "ACTIVE":
        raise ValidationError("The selected department is inactive.")
    units = validate_positive_int(credit_units, "Credit units", 12)
    return dict(code=require_text(code, "Course code", 20).upper().replace(" ", ""),
                title=require_text(title, "Course title", 200), credit_units=units, department_id=department_id,
                level=validate_level(level), semester=validate_semester(semester),
                weekly_minutes=validate_positive_int(weekly_minutes, "Weekly lecture duration (minutes)", 2400),
                required_room_type=validate_room_type(room_type))


def _used_in_timetables(session: Session, course_id: int) -> bool:
    q = (select(func.count(TimetableEntry.id)).join(CourseAssignment, CourseAssignment.id == TimetableEntry.course_assignment_id)
         .where(CourseAssignment.course_id == course_id))
    return (session.scalar(q) or 0) > 0


def create_course(session: Session, actor, code, title, credit_units, department_id, level, semester,
                  weekly_minutes, room_type="STANDARD_CLASSROOM", sessions: Optional[Sequence[int]] = None) -> Course:
    require(actor, Permission.MANAGE_RECORDS)
    data = _fields(session, code, title, credit_units, department_id, level, semester, weekly_minutes, room_type)
    pattern = _validate_sessions(sessions if sessions else default_session_pattern(data["weekly_minutes"]),
                                 data["weekly_minutes"])
    if session.scalar(select(Course.id).where(Course.code == data["code"])):
        raise ValidationError(f"Course code {data['code']} is already in use.")
    course = Course(**data)
    course.sessions = [CourseSession(session_no=i + 1, duration_minutes=d) for i, d in enumerate(pattern)]
    with integrity_guard(session, f"Course code {data['code']} is already in use."):
        session.add(course)
    return course


def update_course(session: Session, actor, course_id: int, code, title, credit_units, department_id, level,
                  semester, weekly_minutes, room_type, sessions: Optional[Sequence[int]] = None) -> Course:
    require(actor, Permission.MANAGE_RECORDS)
    course = get_or_404(session, Course, course_id, "Course")
    data = _fields(session, code, title, credit_units, department_id, level, semester, weekly_minutes, room_type)
    current = [s.duration_minutes for s in course.sessions]
    wanted = list(sessions) if sessions else (current if sum(current) == data["weekly_minutes"]
                                              else default_session_pattern(data["weekly_minutes"]))
    wanted = _validate_sessions(wanted, data["weekly_minutes"])
    other = session.scalar(select(Course.id).where(Course.code == data["code"], Course.id != course_id))
    if other:
        raise ValidationError(f"Course code {data['code']} is already in use.")
    if wanted != current and _used_in_timetables(session, course_id):
        raise ValidationError("The weekly scheduling pattern cannot change because this course appears in "
                              "generated timetables. Deactivate it and create a new course instead.")
    with integrity_guard(session, f"Course code {data['code']} is already in use."):
        for k, v in data.items():
            setattr(course, k, v)
        if wanted != current:
            course.sessions.clear()
            session.flush()
            course.sessions.extend(CourseSession(session_no=i + 1, duration_minutes=d) for i, d in enumerate(wanted))
    return course


def set_course_status(session: Session, actor, course_id: int, active: bool) -> Course:
    require(actor, Permission.MANAGE_RECORDS)
    course = get_or_404(session, Course, course_id, "Course")
    course.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return course


def get_course_sessions(course: Course) -> list[int]:
    return [s.duration_minutes for s in course.sessions] or default_session_pattern(course.weekly_minutes)


def list_courses(session: Session, actor, search: str = "", department_id: Optional[int] = None,
                 level: Optional[int] = None, semester: Optional[str] = None, status: Optional[str] = None) -> list[Course]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(Course).order_by(Course.code)
    if search.strip():
        like = f"%{escape_like(search.strip().lower())}%"
        q = q.where(or_(func.lower(Course.code).like(like, escape="\\"), func.lower(Course.title).like(like, escape="\\")))
    for col, val in ((Course.department_id, department_id), (Course.level, level), (Course.semester, semester),
                     (Course.status, status)):
        if val:
            q = q.where(col == val)
    return list(session.scalars(q))


def course_detail(session: Session, actor, course_id: int) -> dict:
    require(actor, Permission.VIEW_RECORDS)
    course = get_or_404(session, Course, course_id, "Course")
    assignments = list(session.scalars(select(CourseAssignment).where(CourseAssignment.course_id == course_id)))
    return {"course": course, "sessions": get_course_sessions(course), "assignments": assignments}
