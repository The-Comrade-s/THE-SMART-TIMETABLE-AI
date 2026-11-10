from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.enums import ROOM_TYPES, STATUSES, in_list


class Classroom(Base):
    __tablename__ = "classrooms"
    __table_args__ = (
        UniqueConstraint("building", "name", name="uq_room_building_name"),
        CheckConstraint("capacity > 0", name="ck_room_capacity"),
        CheckConstraint(in_list("room_type", ROOM_TYPES), name="ck_room_type"),
        CheckConstraint(in_list("status", STATUSES), name="ck_room_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    building: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    room_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STANDARD_CLASSROOM")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
