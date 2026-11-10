from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.enums import GEN_STATUSES, in_list


class GenerationHistory(Base):
    __tablename__ = "generation_history"
    __table_args__ = (CheckConstraint(in_list("status", GEN_STATUSES), name="ck_gen_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[Optional[int]] = mapped_column(ForeignKey("timetables.id", ondelete="RESTRICT"), index=True)
    configuration_id: Mapped[Optional[int]] = mapped_column(ForeignKey("algorithm_configurations.id", ondelete="SET NULL"))
    initial_fitness: Mapped[Optional[float]] = mapped_column(Float)
    final_fitness: Mapped[Optional[float]] = mapped_column(Float)
    generations: Mapped[Optional[int]] = mapped_column(Integer)
    best_generation: Mapped[Optional[int]] = mapped_column(Integer)
    execution_seconds: Mapped[Optional[float]] = mapped_column(Float)
    hard_violations: Mapped[Optional[int]] = mapped_column(Integer)
    soft_penalty: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="RUNNING")
    termination_reason: Mapped[Optional[str]] = mapped_column(String(120))
    fitness_progress: Mapped[Optional[list]] = mapped_column(JSON)
    constraint_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    executed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    executed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
