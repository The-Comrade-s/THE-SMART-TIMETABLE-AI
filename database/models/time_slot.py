from __future__ import annotations

from datetime import time

from sqlalchemy import Boolean, CheckConstraint, Integer, Time, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TimeSlot(Base):
    """Active time slots define the institution's permitted teaching hours and start-time grid."""
    __tablename__ = "time_slots"
    __table_args__ = (
        UniqueConstraint("day_of_week", "start_time", "end_time", name="uq_time_slot"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_slot_day"),
        CheckConstraint("start_time < end_time", name="ck_slot_interval"),
        CheckConstraint("duration_minutes > 0", name="ck_slot_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
