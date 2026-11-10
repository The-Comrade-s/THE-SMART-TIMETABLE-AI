from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import EMPLOYMENT, STATUSES, in_list


class Lecturer(Base):
    __tablename__ = "lecturers"
    __table_args__ = (
        CheckConstraint(in_list("status", STATUSES), name="ck_lecturer_status"),
        CheckConstraint(in_list("employment_status", EMPLOYMENT), name="ck_lecturer_employment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="FULL_TIME")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    department: Mapped["Department"] = relationship(back_populates="lecturers")  # noqa: F821

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
