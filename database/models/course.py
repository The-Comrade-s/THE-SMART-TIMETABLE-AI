from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import LEVELS, ROOM_TYPES, SEMESTERS, STATUSES, in_list


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("credit_units BETWEEN 1 AND 12", name="ck_course_units"),
        CheckConstraint("weekly_minutes > 0", name="ck_course_weekly_minutes"),
        CheckConstraint(in_list("level", LEVELS), name="ck_course_level"),
        CheckConstraint(in_list("semester", SEMESTERS), name="ck_course_semester"),
        CheckConstraint(in_list("required_room_type", ROOM_TYPES), name="ck_course_room_type"),
        CheckConstraint(in_list("status", STATUSES), name="ck_course_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    credit_units: Mapped[int] = mapped_column(Integer, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[str] = mapped_column(String(10), nullable=False)
    weekly_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    required_room_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STANDARD_CLASSROOM")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    department: Mapped["Department"] = relationship(back_populates="courses")  # noqa: F821
    sessions: Mapped[List["CourseSession"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="CourseSession.session_no")


class CourseSession(Base):
    """One weekly teaching session of a course (defines number and length of sessions)."""
    __tablename__ = "course_sessions"
    __table_args__ = (
        UniqueConstraint("course_id", "session_no", name="uq_course_session"),
        CheckConstraint("duration_minutes > 0", name="ck_session_duration"),
        CheckConstraint("session_no >= 1", name="ck_session_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    session_no: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="sessions")
