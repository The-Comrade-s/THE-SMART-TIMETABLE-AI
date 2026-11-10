from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

HARD_CODES = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10")
SOFT_CODES = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
HARD_LABELS = {
    "H1": "Lecturer conflicts", "H2": "Classroom conflicts", "H3": "Student group conflicts",
    "H4": "Lecturer availability violations", "H5": "Classroom availability violations",
    "H6": "Room capacity violations", "H7": "Room type violations", "H8": "Working-hour violations",
    "H9": "Session duration violations", "H10": "Missing sessions",
}
SOFT_LABELS = {
    "S1": "Lecturer preferences", "S2": "Weekly distribution", "S3": "Student group gaps",
    "S4": "Lecturer gaps", "S5": "Consecutive lecture limits", "S6": "Classroom utilisation",
    "S7": "Daily workload balance",
}


class ConfigurationError(ValueError):
    pass


def _default_weights(codes) -> Dict[str, float]:
    return {c: 1.0 for c in codes}


@dataclass
class GAConfig:
    population_size: int = 40
    max_generations: int = 100
    mutation_rate: float = 0.02
    crossover_rate: float = 0.85
    elite_size: int = 2
    tournament_size: int = 3
    stagnation_threshold: int = 40
    target_fitness: float = 1.0
    stop_on_zero_hard: bool = False
    hard_factor: float = 1000.0
    soft_factor: float = 1.0
    heuristic_ratio: float = 0.5
    hard_weights: Dict[str, float] = field(default_factory=lambda: _default_weights(HARD_CODES))
    soft_weights: Dict[str, float] = field(default_factory=lambda: _default_weights(SOFT_CODES))
    seed: Optional[int] = None

    def __post_init__(self):
        self.hard_weights = {**_default_weights(HARD_CODES), **(self.hard_weights or {})}
        self.soft_weights = {**_default_weights(SOFT_CODES), **(self.soft_weights or {})}

    def validate(self) -> "GAConfig":
        def chk(cond: bool, msg: str):
            if not cond:
                raise ConfigurationError(msg)
        chk(isinstance(self.population_size, int) and 4 <= self.population_size <= 2000, "Population size must be between 4 and 2000.")
        chk(isinstance(self.max_generations, int) and 1 <= self.max_generations <= 20000, "Maximum generations must be between 1 and 20000.")
        chk(0.0 <= self.mutation_rate <= 1.0, "Mutation rate must be between 0 and 1.")
        chk(0.0 <= self.crossover_rate <= 1.0, "Crossover rate must be between 0 and 1.")
        chk(0 <= self.elite_size < self.population_size, "Elite size must be at least 0 and smaller than the population size.")
        chk(2 <= self.tournament_size <= self.population_size, "Tournament size must be between 2 and the population size.")
        chk(self.stagnation_threshold >= 1, "Stagnation threshold must be at least 1 generation.")
        chk(0.0 < self.target_fitness <= 1.0, "Target fitness must be greater than 0 and at most 1.")
        chk(self.soft_factor > 0 and self.hard_factor >= 10 * self.soft_factor,
            "The hard-constraint factor must be at least 10 times the soft-constraint factor.")
        chk(0.0 <= self.heuristic_ratio <= 1.0, "Heuristic ratio must be between 0 and 1.")
        for w in list(self.hard_weights.values()) + list(self.soft_weights.values()):
            chk(isinstance(w, (int, float)) and w >= 0, "Constraint weights must be zero or positive numbers.")
        chk(all(self.hard_weights[c] > 0 for c in HARD_CODES), "Hard constraint weights must be greater than zero.")
        return self

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "population_size", "max_generations", "mutation_rate", "crossover_rate", "elite_size", "tournament_size",
            "stagnation_threshold", "target_fitness", "stop_on_zero_hard", "hard_factor", "soft_factor",
            "heuristic_ratio", "hard_weights", "soft_weights", "seed")}
