from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import SEMESTERS, STATUSES, in_list


class CourseAssignment(Base):
    __tablename__ = "course_assignments"
    __table_args__ = (
        UniqueConstraint("course_id", "lecturer_id", "group_id", "academic_session", "semester", name="uq_assignment"),
        CheckConstraint(in_list("semester", SEMESTERS), name="ck_assignment_semester"),
        CheckConstraint(in_list("status", STATUSES), name="ck_assignment_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id", ondelete="RESTRICT"), nullable=False, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("student_groups.id", ondelete="RESTRICT"), nullable=False, index=True)
    academic_session: Mapped[str] = mapped_column(String(20), nullable=False)
    semester: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    course: Mapped["Course"] = relationship()  # noqa: F821
    lecturer: Mapped["Lecturer"] = relationship()  # noqa: F821
    group: Mapped["StudentGroup"] = relationship()  # noqa: F821
