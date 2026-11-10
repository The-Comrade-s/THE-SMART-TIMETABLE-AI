"""Initial population: heuristic greedy placement mixed with constrained-random placement."""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from algorithm.chromosome import Chromosome, Gene, make_gene, unplaced_gene
from algorithm.data import SchedulingData


class Occupancy:
    """Tracks busy intervals per lecturer / room / group / day for fast clash tests."""

    def __init__(self) -> None:
        self.busy: Dict[Tuple[str, int, int], List[Tuple[int, int]]] = {}

    @staticmethod
    def _keys(gene_like, room, day):
        return (("L", gene_like.lecturer_id, day), ("R", room, day), ("G", gene_like.group_id, day))

    def clashes(self, req, room: int, day: int, s: int, e: int) -> int:
        n = 0
        for key in self._keys(req, room, day):
            for bs, be in self.busy.get(key, ()):
                if s < be and bs < e:
                    n += 1
        return n

    def add(self, req, room: int, day: int, s: int, e: int) -> None:
        for key in self._keys(req, room, day):
            self.busy.setdefault(key, []).append((s, e))

    def remove(self, req, room: int, day: int, s: int, e: int) -> None:
        for key in self._keys(req, room, day):
            lst = self.busy.get(key)
            if lst and (s, e) in lst:
                lst.remove((s, e))


def _pick_clear_option(data: SchedulingData, req, occ: Occupancy, rng: random.Random, sample: int = 80) -> Optional[Tuple[int, int, int]]:
    options = data.domains[req.index]
    if not options:
        return None
    pool = rng.sample(options, min(sample, len(options)))
    for opt in pool:
        if occ.clashes(req, opt[0], opt[1], opt[2], opt[2] + req.duration) == 0:
            return opt
    shuffled = list(options)
    rng.shuffle(shuffled)
    best, best_c = None, 10 ** 9
    for opt in shuffled:
        c = occ.clashes(req, opt[0], opt[1], opt[2], opt[2] + req.duration)
        if c == 0:
            return opt
        if c < best_c:
            best, best_c = opt, c
    return best


def heuristic_individual(data: SchedulingData, rng: random.Random) -> Chromosome:
    """Most constrained sessions first (fewest options, longest, biggest group), clash-free where possible."""
    order = sorted(range(len(data.sessions)),
                   key=lambda i: (len(data.domains[i]), -data.sessions[i].duration, -data.sessions[i].population, rng.random()))
    genes: List[Gene] = [None] * len(data.sessions)  # type: ignore[list-item]
    occ = Occupancy()
    for i in order:
        req = data.sessions[i]
        opt = _pick_clear_option(data, req, occ, rng)
        if opt is None:
            genes[i] = unplaced_gene(data, i)
        else:
            genes[i] = make_gene(data, i, *opt)
            occ.add(req, opt[0], opt[1], opt[2], opt[2] + req.duration)
    return Chromosome(genes)


def random_individual(data: SchedulingData, rng: random.Random) -> Chromosome:
    """Constrained random: every gene is drawn from its feasible domain (static constraints hold)."""
    genes = []
    for i in range(len(data.sessions)):
        options = data.domains[i]
        genes.append(make_gene(data, i, *rng.choice(options)) if options else unplaced_gene(data, i))
    return Chromosome(genes)


def initial_population(data: SchedulingData, size: int, heuristic_ratio: float, rng: random.Random,
                       seeds: Optional[List[Chromosome]] = None) -> List[Chromosome]:
    pop: List[Chromosome] = [s.copy() for s in (seeds or [])][:size]
    n_heur = int(round((size - len(pop)) * heuristic_ratio))
    for _ in range(n_heur):
        pop.append(heuristic_individual(data, rng))
    while len(pop) < size:
        pop.append(random_individual(data, rng))
    return pop


def unplaceable_report(data: SchedulingData) -> List[dict]:
    """Reasons for sessions that cannot be placed at all (never silently discarded)."""
    out = []
    for idx, reason in sorted(data.unplaceable.items()):
        r = data.sessions[idx]
        out.append({"assignment_id": r.assignment_id, "session_no": r.session_no, "course": r.course_code, "reason": reason})
    return out
