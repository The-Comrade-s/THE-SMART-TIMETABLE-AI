from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.enums import STATUSES, in_list


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (CheckConstraint(in_list("status", STATUSES), name="ck_department_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    faculty: Mapped[Optional[str]] = mapped_column(String(150))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    lecturers: Mapped[List["Lecturer"]] = relationship(back_populates="department")  # noqa: F821
    courses: Mapped[List["Course"]] = relationship(back_populates="department")  # noqa: F821
