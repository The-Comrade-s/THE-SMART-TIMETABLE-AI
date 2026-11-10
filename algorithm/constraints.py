"""Hard (H1-H10) and soft (S1-S7) constraint evaluation with interval-based overlap detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set, Tuple

from algorithm.chromosome import Gene
from algorithm.configuration import HARD_CODES, SOFT_CODES
from algorithm.data import SchedulingData
from algorithm.intervals import contains, count_overlapping_pairs

LECTURER_GAP_FREE_MIN = 60      # idle time up to 1 hour between lecturer sessions is acceptable
MAX_LECTURER_CHAIN_MIN = 240
MAX_GROUP_CHAIN_MIN = 240
MAX_LECTURER_DAY_MIN = 240
MAX_GROUP_DAY_MIN = 360


@dataclass
class ConstraintReport:
    hard: Dict[str, int] = field(default_factory=lambda: {c: 0 for c in HARD_CODES})
    soft: Dict[str, float] = field(default_factory=lambda: {c: 0.0 for c in SOFT_CODES})
    conflict_genes: Set[int] = field(default_factory=set)

    @property
    def hard_total(self) -> int:
        return sum(self.hard.values())


def _by_resource(genes: Sequence[Gene], attr: str) -> Dict[Tuple[int, int], List[Tuple[int, int, int]]]:
    buckets: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}
    for g in genes:
        if g.placed:
            buckets.setdefault((getattr(g, attr), g.day), []).append((g.start, g.end, g.req_index))
    return buckets


def evaluate_constraints(genes: Sequence[Gene], data: SchedulingData) -> ConstraintReport:
    rep = ConstraintReport()
    # H10 completeness and static hard constraints (H4-H9)
    for g in genes:
        if not g.placed:
            rep.hard["H10"] += 1
            rep.conflict_genes.add(g.req_index)
            continue
        if (g.room_id, g.day, g.start) in data.domain_sets[g.req_index] and g.end - g.start == data.sessions[g.req_index].duration:
            continue
        for code in data.static_violations(data.sessions[g.req_index], g.room_id, g.day, g.start, g.end):
            rep.hard[code] += 1
            rep.conflict_genes.add(g.req_index)
    # H1-H3 interval overlaps (partial overlaps included)
    for code, attr in (("H1", "lecturer_id"), ("H2", "room_id"), ("H3", "group_id")):
        for items in _by_resource(genes, attr).values():
            if len(items) > 1:
                pairs, tags = count_overlapping_pairs(items)
                rep.hard[code] += pairs
                rep.conflict_genes.update(tags)
    _soft(genes, data, rep)
    return rep


def _gaps_and_chains(items: List[Tuple[int, int, int]]):
    ordered = sorted(items)
    gaps, chains, chain = [], [], ordered[0][1] - ordered[0][0]
    for (s0, e0, _), (s1, e1, _) in zip(ordered, ordered[1:]):
        gap = s1 - e0
        if gap > 0:
            gaps.append(gap)
        if gap <= 0:
            chain += e1 - s1
        else:
            chains.append(chain)
            chain = e1 - s1
    chains.append(chain)
    return gaps, chains


def _soft(genes: Sequence[Gene], data: SchedulingData, rep: ConstraintReport) -> None:
    placed = [g for g in genes if g.placed]
    s = rep.soft
    # S1 lecturer preferences: sessions outside a lecturer's preferred periods (only if they declared any)
    for g in placed:
        pref = data.lecturer_preferred.get(g.lecturer_id)
        if pref and not contains(pref.get(g.day, []), g.start, g.end):
            s["S1"] += 1.0
    # S2 distribution of teaching minutes across the permitted weekdays
    days = sorted(data.windows)
    if days and placed:
        load = {d: 0 for d in days}
        for g in placed:
            load[g.day] = load.get(g.day, 0) + (g.end - g.start)
        mean = sum(load.values()) / len(load)
        s["S2"] = sum(abs(v - mean) for v in load.values()) / 60.0
    # S3 student gaps, S5 consecutive limits (groups)
    for items in _by_resource(placed, "group_id").values():
        gaps, chains = _gaps_and_chains(items)
        s["S3"] += sum(gaps) / 60.0
        s["S5"] += sum(max(0, c - MAX_GROUP_CHAIN_MIN) for c in chains) / 60.0
        total = sum(e - st for st, e, _ in items)
        s["S7"] += max(0, total - MAX_GROUP_DAY_MIN) / 60.0
    # S4 lecturer gaps, S5 lecturer chains, S7 lecturer daily load
    for items in _by_resource(placed, "lecturer_id").values():
        gaps, chains = _gaps_and_chains(items)
        s["S4"] += sum(max(0, g - LECTURER_GAP_FREE_MIN) for g in gaps) / 60.0
        s["S5"] += sum(max(0, c - MAX_LECTURER_CHAIN_MIN) for c in chains) / 60.0
        total = sum(e - st for st, e, _ in items)
        s["S7"] += max(0, total - MAX_LECTURER_DAY_MIN) / 60.0
    # S6 classroom utilisation: wasted seats as a fraction of capacity
    for g in placed:
        room = data.rooms.get(g.room_id)
        if room and room.capacity > 0:
            s["S6"] += max(0.0, (room.capacity - data.sessions[g.req_index].population) / room.capacity)
