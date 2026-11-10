"""Chromosome = one complete candidate timetable. Gene i always describes required session i."""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Sequence, Tuple

from algorithm.data import SchedulingData

UNPLACED = -1


class Gene(NamedTuple):
    req_index: int
    assignment_id: int
    session_no: int
    lecturer_id: int
    group_id: int
    room_id: Optional[int]
    day: int
    start: int
    end: int

    @property
    def placed(self) -> bool:
        return self.room_id is not None and self.day != UNPLACED


def make_gene(data: SchedulingData, index: int, room_id: Optional[int], day: int, start: int) -> Gene:
    r = data.sessions[index]
    if room_id is None:
        return Gene(index, r.assignment_id, r.session_no, r.lecturer_id, r.group_id, None, UNPLACED, UNPLACED, UNPLACED)
    return Gene(index, r.assignment_id, r.session_no, r.lecturer_id, r.group_id, room_id, day, start, start + r.duration)


def unplaced_gene(data: SchedulingData, index: int) -> Gene:
    return make_gene(data, index, None, UNPLACED, UNPLACED)


class Chromosome:
    __slots__ = ("genes", "evaluation", "hint")

    def __init__(self, genes: List[Gene]):
        self.genes = genes
        self.evaluation = None   # set by the fitness evaluator
        self.hint: frozenset = frozenset()  # gene indices believed to be in conflict (inherited)

    @property
    def fitness(self) -> float:
        return self.evaluation.fitness

    @property
    def rank_key(self) -> Tuple[int, float]:
        """Higher is better: fewer hard violations always dominates, then higher fitness."""
        return (-self.evaluation.hard_total, self.evaluation.fitness)

    def key(self) -> Tuple:
        return tuple((g.room_id, g.day, g.start) for g in self.genes)

    def copy(self) -> "Chromosome":
        c = Chromosome(list(self.genes))
        c.hint = self.hint
        return c

    def is_complete(self, data: SchedulingData) -> bool:
        return (len(self.genes) == len(data.sessions)
                and all(g.req_index == i and g.assignment_id == data.sessions[i].assignment_id
                        and g.session_no == data.sessions[i].session_no for i, g in enumerate(self.genes)))


def validate_structure(chrom: Chromosome, data: SchedulingData) -> None:
    if not chrom.is_complete(data):
        raise ValueError("Chromosome does not contain every required session in order.")
