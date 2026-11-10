from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class AlgorithmConfiguration(Base):
    __tablename__ = "algorithm_configurations"
    __table_args__ = (
        CheckConstraint("population_size >= 4", name="ck_cfg_pop"),
        CheckConstraint("max_generations >= 1", name="ck_cfg_gen"),
        CheckConstraint("mutation_rate >= 0 AND mutation_rate <= 1", name="ck_cfg_mut"),
        CheckConstraint("crossover_rate >= 0 AND crossover_rate <= 1", name="ck_cfg_cross"),
        CheckConstraint("elite_size >= 0 AND elite_size < population_size", name="ck_cfg_elite"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Unnamed configuration")
    population_size: Mapped[int] = mapped_column(Integer, nullable=False)
    max_generations: Mapped[int] = mapped_column(Integer, nullable=False)
    mutation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    crossover_rate: Mapped[float] = mapped_column(Float, nullable=False)
    elite_size: Mapped[int] = mapped_column(Integer, nullable=False)
    tournament_size: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    stagnation_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    target_fitness: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    stop_on_zero_hard: Mapped[bool] = mapped_column(nullable=False, default=False)
    hard_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    soft_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    hard_weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    soft_weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
