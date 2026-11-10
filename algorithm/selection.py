from __future__ import annotations

import random
from typing import List, Tuple

from algorithm.chromosome import Chromosome


def tournament_select(population: List[Chromosome], k: int, rng: random.Random) -> Chromosome:
    contenders = rng.sample(population, min(k, len(population)))
    return max(contenders, key=lambda c: c.rank_key)


def select_parents(population: List[Chromosome], k: int, rng: random.Random) -> Tuple[Chromosome, Chromosome]:
    """Two tournaments; the second parent is re-drawn (a few times) so a single individual is not paired with itself."""
    a = tournament_select(population, k, rng)
    b = tournament_select(population, k, rng)
    for _ in range(4):
        if b is not a and b.key() != a.key():
            break
        b = tournament_select(population, k, rng)
    return a, b
