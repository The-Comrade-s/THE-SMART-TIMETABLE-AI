"""Dashboard metrics and chart data, all from real database queries."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, has_permission, require
from database.models import (Classroom, Course, Department, GenerationHistory, Lecturer, StudentGroup, Timetable)


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def metrics(session: Session, actor) -> dict:
    require(actor, Permission.VIEW_RECORDS)
    return {
        "departments": _count(session, Department), "lecturers": _count(session, Lecturer),
        "courses": _count(session, Course), "classrooms": _count(session, Classroom),
        "student_groups": _count(session, StudentGroup), "timetables": _count(session, Timetable),
        "published": _count(session, Timetable, Timetable.status == "PUBLISHED"),
        "draft": _count(session, Timetable, Timetable.status.in_(("DRAFT", "GENERATED", "VALIDATED"))),
    }


def viewer_metrics(session: Session, actor) -> dict:
    require(actor, Permission.VIEW_PUBLISHED)
    return {"published": _count(session, Timetable, Timetable.status == "PUBLISHED")}


def courses_per_department(session: Session, actor) -> list[tuple[str, int]]:
    require(actor, Permission.VIEW_RECORDS)
    q = (select(Department.code, func.count(Course.id)).join(Course, Course.department_id == Department.id)
         .group_by(Department.code).order_by(Department.code))
    return [(c, n) for c, n in session.execute(q)]


def lecturers_per_department(session: Session, actor) -> list[tuple[str, int]]:
    require(actor, Permission.VIEW_RECORDS)
    q = (select(Department.code, func.count(Lecturer.id)).join(Lecturer, Lecturer.department_id == Department.id)
         .group_by(Department.code).order_by(Department.code))
    return [(c, n) for c, n in session.execute(q)]


def classroom_capacities(session: Session, actor) -> list[int]:
    require(actor, Permission.VIEW_RECORDS)
    return list(session.scalars(select(Classroom.capacity)))


def generation_runs(session: Session, actor, limit: int = 30) -> list[GenerationHistory]:
    require(actor, Permission.VIEW_HISTORY)
    rows = list(session.scalars(select(GenerationHistory).where(GenerationHistory.status.in_(("COMPLETED", "INTERRUPTED")))
                                .order_by(GenerationHistory.executed_at.desc(), GenerationHistory.id.desc()).limit(limit)))
    return list(reversed(rows))
