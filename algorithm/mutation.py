"""Mutation operators. Every mutation draws from the session's feasible domain, so required sessions are
never removed and assignment relationships are never changed.

Operators: move (new room/day/start), room change, time shift (day/start), and conflict repair
(re-place a conflicting session at a clash-free option). Genes inherited as conflicting are mutated with
a boosted probability (targeted mutation).
"""
from __future__ import annotations

import random
from typing import Optional

from algorithm.chromosome import Chromosome, make_gene
from algorithm.data import SchedulingData
from algorithm.initialization import Occupancy, _pick_clear_option

TARGET_BOOST = 4.0


def _occupancy(chrom: Chromosome, data: SchedulingData) -> Occupancy:
    occ = Occupancy()
    for g in chrom.genes:
        if g.placed:
            occ.add(data.sessions[g.req_index], g.room_id, g.day, g.start, g.end)
    return occ


def mutate(chrom: Chromosome, data: SchedulingData, rate: float, rng: random.Random) -> int:
    """Mutate in place; returns the number of genes changed."""
    changed = 0
    occ: Optional[Occupancy] = None
    for i, g in enumerate(chrom.genes):
        domain = data.domains[i]
        if not domain:
            continue
        p = min(1.0, rate * TARGET_BOOST) if i in chrom.hint else rate
        if rng.random() >= p:
            continue
        req = data.sessions[i]
        op = rng.random()
        if i in chrom.hint and op < 0.5:
            if occ is None:
                occ = _occupancy(chrom, data)
            if g.placed:
                occ.remove(req, g.room_id, g.day, g.start, g.end)
            opt = _pick_clear_option(data, req, occ, rng)
        elif g.placed and op < 0.7:      # change room only
            same_time = [o for o in domain if o[1] == g.day and o[2] == g.start and o[0] != g.room_id]
            opt = rng.choice(same_time) if same_time else rng.choice(domain)
        elif g.placed and op < 0.85:     # shift in time, keep room
            same_room = [o for o in domain if o[0] == g.room_id and (o[1], o[2]) != (g.day, g.start)]
            opt = rng.choice(same_room) if same_room else rng.choice(domain)
        else:
            opt = rng.choice(domain)
        if opt is None:
            continue
        chrom.genes[i] = make_gene(data, i, *opt)
        changed += 1
        if occ is not None:
            occ.add(req, opt[0], opt[1], opt[2], opt[2] + req.duration)
    return changed
