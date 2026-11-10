"""Assignment-block uniform crossover.

Genes are grouped by course assignment. For each block the child takes ALL of that assignment's sessions
from one parent. Because gene i always describes required session i, every child contains exactly the
required sessions (no repair needed) and the course/lecturer/group relationships never change.
"""
from __future__ import annotations

import random
from typing import Tuple

from algorithm.chromosome import Chromosome
from algorithm.data import SchedulingData


def block_crossover(a: Chromosome, b: Chromosome, data: SchedulingData, rng: random.Random) -> Tuple[Chromosome, Chromosome]:
    g1, g2 = list(a.genes), list(b.genes)
    h1, h2 = set(a.evaluation.conflict_genes), set(b.evaluation.conflict_genes)
    n1, n2 = set(), set()
    for block in data.blocks:
        if rng.random() < 0.5:
            for i in block:
                g1[i], g2[i] = b.genes[i], a.genes[i]
            n1.update(i for i in block if i in h2)
            n2.update(i for i in block if i in h1)
        else:
            n1.update(i for i in block if i in h1)
            n2.update(i for i in block if i in h2)
    c1, c2 = Chromosome(g1), Chromosome(g2)
    c1.hint, c2.hint = frozenset(n1), frozenset(n2)
    return c1, c2
