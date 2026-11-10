"""Fitness(T) = 1 / (1 + WH*H + WS*S), where H = sum_i w_i*h_i (hard) and S = sum_j v_j*s_j (soft)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from algorithm.chromosome import Chromosome, Gene
from algorithm.configuration import GAConfig, HARD_CODES, HARD_LABELS, SOFT_CODES, SOFT_LABELS
from algorithm.constraints import ConstraintReport, evaluate_constraints
from algorithm.data import SchedulingData


@dataclass
class Evaluation:
    fitness: float
    hard_total: int                 # unweighted count of hard violations
    hard_weighted: float            # H
    soft_weighted: float            # S
    hard: Dict[str, int]
    soft: Dict[str, float]
    conflict_genes: frozenset

    def breakdown(self) -> dict:
        return {"hard": {HARD_LABELS[c]: self.hard[c] for c in HARD_CODES},
                "soft": {SOFT_LABELS[c]: round(self.soft[c], 4) for c in SOFT_CODES},
                "hard_total": self.hard_total, "hard_weighted": self.hard_weighted,
                "soft_weighted": round(self.soft_weighted, 4), "fitness": self.fitness}


def fitness_value(hard_weighted: float, soft_weighted: float, hard_factor: float, soft_factor: float) -> float:
    return 1.0 / (1.0 + hard_factor * hard_weighted + soft_factor * soft_weighted)


class FitnessEvaluator:
    """Deterministic evaluator with a memo cache keyed by gene placement."""

    def __init__(self, data: SchedulingData, config: GAConfig, cache_size: int = 50000):
        self.data, self.config = data, config
        self._cache: Dict[tuple, Evaluation] = {}
        self._cache_size = cache_size
        self.evaluations = 0
        self.cache_hits = 0

    def evaluate_genes(self, genes: Sequence[Gene]) -> Evaluation:
        rep: ConstraintReport = evaluate_constraints(genes, self.data)
        c = self.config
        h = sum(c.hard_weights[k] * v for k, v in rep.hard.items())
        s = sum(c.soft_weights[k] * v for k, v in rep.soft.items())
        return Evaluation(fitness_value(h, s, c.hard_factor, c.soft_factor), rep.hard_total, h, s,
                          dict(rep.hard), dict(rep.soft), frozenset(rep.conflict_genes))

    def evaluate(self, chrom: Chromosome) -> Evaluation:
        key = chrom.key()
        ev = self._cache.get(key)
        if ev is None:
            ev = self.evaluate_genes(chrom.genes)
            self.evaluations += 1
            if len(self._cache) >= self._cache_size:
                self._cache.clear()
            self._cache[key] = ev
        else:
            self.cache_hits += 1
        chrom.evaluation = ev
        return ev
