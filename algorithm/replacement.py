from __future__ import annotations

from typing import List

from algorithm.chromosome import Chromosome


def ranked_indices(population: List[Chromosome]) -> List[int]:
    """Indices best-first. Deterministic: ties are broken by original position."""
    return sorted(range(len(population)), key=lambda i: (population[i].rank_key, -i), reverse=True)


def elites(population: List[Chromosome], count: int) -> List[Chromosome]:
    return [population[i] for i in ranked_indices(population)[:count]]


def next_generation(population: List[Chromosome], offspring: List[Chromosome], elite_size: int) -> List[Chromosome]:
    """Elites survive unchanged; offspring fill the remaining slots, so the size stays constant."""
    return (elites(population, elite_size) + offspring)[:len(population)]


def inject_diversity(population: List[Chromosome], fresh: List[Chromosome], protect: int) -> List[Chromosome]:
    """Replace the worst unprotected individuals with fresh ones (population size is unchanged)."""
    order = ranked_indices(population)
    victims = order[protect:][::-1]      # worst first, never the protected top individuals
    out = list(population)
    for idx, new in zip(victims, fresh):
        out[idx] = new
    return out
