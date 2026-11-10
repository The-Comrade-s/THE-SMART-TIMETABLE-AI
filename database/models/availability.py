from __future__ import annotations

from datetime import time

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.enums import AVAILABILITY, in_list


class LecturerAvailability(Base):
    __tablename__ = "lecturer_availability"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_lav_day"),
        CheckConstraint("start_time < end_time", name="ck_lav_interval"),
        CheckConstraint(in_list("status", AVAILABILITY), name="ck_lav_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="AVAILABLE")


class RoomAvailability(Base):
    __tablename__ = "room_availability"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_rav_day"),
        CheckConstraint("start_time < end_time", name="ck_rav_interval"),
        CheckConstraint(in_list("status", AVAILABILITY), name="ck_rav_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="AVAILABLE")
