from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import LEVELS, SEMESTERS, TIMETABLE_STATUSES, in_list


class Timetable(Base):
    __tablename__ = "timetables"
    __table_args__ = (
        CheckConstraint(in_list("status", TIMETABLE_STATUSES), name="ck_tt_status"),
        CheckConstraint(in_list("semester", SEMESTERS), name="ck_tt_semester"),
        CheckConstraint("version >= 1", name="ck_tt_version"),
        Index("ix_tt_scope", "academic_session", "semester", "department_id", "level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    academic_session: Mapped[str] = mapped_column(String(20), nullable=False)
    semester: Mapped[str] = mapped_column(String(10), nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    level: Mapped[Optional[int]] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("timetables.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    fitness_score: Mapped[Optional[float]] = mapped_column(Float)
    generation_number: Mapped[Optional[int]] = mapped_column(Integer)
    hard_violations: Mapped[Optional[int]] = mapped_column(Integer)
    soft_penalty: Mapped[Optional[float]] = mapped_column(Float)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_summary: Mapped[Optional[dict]] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    published_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    entries: Mapped[list["TimetableEntry"]] = relationship(back_populates="timetable")
    department: Mapped[Optional["Department"]] = relationship()  # noqa: F821


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_entry_day"),
        CheckConstraint("start_time < end_time", name="ck_entry_interval"),
        Index("ix_entry_tt_day", "timetable_id", "day_of_week"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[int] = mapped_column(ForeignKey("timetables.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_assignment_id: Mapped[int] = mapped_column(ForeignKey("course_assignments.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="RESTRICT"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    generation_metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    timetable: Mapped["Timetable"] = relationship(back_populates="entries")
    assignment: Mapped["CourseAssignment"] = relationship()  # noqa: F821
    classroom: Mapped["Classroom"] = relationship()  # noqa: F821


class TimetableAudit(Base):
    __tablename__ = "timetable_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[int] = mapped_column(ForeignKey("timetables.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    details: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
