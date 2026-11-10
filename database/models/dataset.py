"""Imported institutional datasets and the examination-timetable source tables.

Examination records live in their own tables (exam_*): they have dates, sessions and no rooms or lecturers, so they do not
fit the lecture-timetable tables. Lecture-timetable test data (synthetic) reuses the existing Department, Course, Lecturer,
Classroom, StudentGroup, CourseAssignment and Timetable tables and is tracked through `dataset_members`.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import in_list

DATASET_TYPES = ("EXAM_TIMETABLE_SOURCE", "SYNTHETIC_LECTURE_TEST")
IMPORT_STATUSES = ("IMPORTED", "FAILED")
VALIDATION_STATUSES = ("NOT_VALIDATED", "VALID", "NEEDS_REVIEW", "INVALID")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("dataset_type", "source_sha256", name="uq_dataset_source"),
        CheckConstraint(in_list("dataset_type", DATASET_TYPES), name="ck_dataset_type"),
        CheckConstraint(in_list("import_status", IMPORT_STATUSES), name="ck_dataset_import_status"),
        CheckConstraint(in_list("validation_status", VALIDATION_STATUSES), name="ck_dataset_validation_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_document: Mapped[Optional[str]] = mapped_column(String(255))
    source_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    is_draft_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parent_dataset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"))
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    import_status: Mapped[str] = mapped_column(String(10), nullable=False, default="IMPORTED")
    validation_status: Mapped[str] = mapped_column(String(15), nullable=False, default="NOT_VALIDATED")
    report: Mapped[Optional[dict]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    imported_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class DatasetMember(Base):
    """Ties records of the existing lecture tables to the synthetic dataset that created them (safe removal)."""
    __tablename__ = "dataset_members"
    __table_args__ = (UniqueConstraint("dataset_id", "entity", "entity_id", name="uq_dataset_member"),
                      Index("ix_dataset_member_entity", "entity", "entity_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255))


class ExamDay(Base):
    __tablename__ = "exam_days"
    __table_args__ = (UniqueConstraint("dataset_id", "day_no", name="uq_exam_day"),
                      CheckConstraint("day_no >= 1", name="ck_exam_day_no"))

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    exam_date: Mapped[Optional[date]] = mapped_column(Date)
    weekday: Mapped[str] = mapped_column(String(15), nullable=False)
    date_text: Mapped[str] = mapped_column(String(60), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    faculty_group_code: Mapped[Optional[str]] = mapped_column(String(20))
    faculty_group_text: Mapped[Optional[str]] = mapped_column(Text)
    review_notes: Mapped[Optional[list]] = mapped_column(JSON)

    sessions: Mapped[list["ExamSession"]] = relationship(back_populates="day", cascade="all, delete-orphan",
                                                         order_by="ExamSession.slot_no")


class ExamSession(Base):
    __tablename__ = "exam_sessions"
    __table_args__ = (UniqueConstraint("day_id", "slot_no", name="uq_exam_session"),
                      CheckConstraint("slot_no BETWEEN 1 AND 3", name="ck_exam_slot"))

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("exam_days.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label_printed: Mapped[str] = mapped_column(String(15), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)

    day: Mapped["ExamDay"] = relationship(back_populates="sessions")
    entries: Mapped[list["ExamEntry"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ExamEntry(Base):
    __tablename__ = "exam_entries"
    __table_args__ = (UniqueConstraint("dataset_id", "record_key", name="uq_exam_entry_key"),
                      Index("ix_exam_entry_code", "course_code"))

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("exam_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    record_key: Mapped[str] = mapped_column(String(40), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_in_column: Mapped[int] = mapped_column(Integer, nullable=False)
    course_code: Mapped[str] = mapped_column(String(40), nullable=False)      # exactly as printed; empty string if missing
    course_title: Mapped[str] = mapped_column(String(300), nullable=False)     # exactly as printed; empty string if missing
    base_code: Mapped[str] = mapped_column(String(40), nullable=False)         # reference only, records are never merged
    batch: Mapped[Optional[str]] = mapped_column(String(1))
    noun_prefixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reasons: Mapped[Optional[list]] = mapped_column(JSON)
    informational: Mapped[Optional[list]] = mapped_column(JSON)

    session: Mapped["ExamSession"] = relationship(back_populates="entries")
