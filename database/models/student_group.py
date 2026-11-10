from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import LEVELS, STATUSES, in_list


class StudentGroup(Base):
    __tablename__ = "student_groups"
    __table_args__ = (
        UniqueConstraint("name", "academic_session", name="uq_group_name_session"),
        CheckConstraint("population > 0", name="ck_group_population"),
        CheckConstraint(in_list("level", LEVELS), name="ck_group_level"),
        CheckConstraint(in_list("status", STATUSES), name="ck_group_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    programme: Mapped[str] = mapped_column(String(150), nullable=False)
    population: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_session: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    department: Mapped["Department"] = relationship()  # noqa: F821
