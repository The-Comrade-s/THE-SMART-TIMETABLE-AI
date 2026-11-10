"""Interval arithmetic on minutes-since-midnight (half-open intervals [start, end))."""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

Interval = Tuple[int, int]


def merge(intervals: Iterable[Interval]) -> List[Interval]:
    out: List[Interval] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(base: Sequence[Interval], cut: Sequence[Interval]) -> List[Interval]:
    result: List[Interval] = []
    for s, e in base:
        pieces = [(s, e)]
        for cs, ce in cut:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt
        result.extend(pieces)
    return merge(result)


def contains(intervals: Sequence[Interval], start: int, end: int) -> bool:
    """True when [start, end) lies completely inside ONE interval of the (merged) list."""
    for s, e in intervals:
        if s <= start and end <= e:
            return True
    return False


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Partial overlaps count: 08:00-10:00 and 09:00-11:00 overlap; 08:00-09:00 and 09:00-10:00 do not."""
    return a_start < b_end and b_start < a_end


def count_overlapping_pairs(items: Sequence[Tuple[int, int, int]]) -> Tuple[int, List[int]]:
    """items: (start, end, tag). Returns (pair_count, tags_involved). Sweep over start-sorted items."""
    ordered = sorted(items)
    pairs, tags = 0, []
    for i in range(len(ordered)):
        si, ei, ti = ordered[i]
        for j in range(i + 1, len(ordered)):
            sj, ej, tj = ordered[j]
            if sj >= ei:
                break
            pairs += 1
            tags.extend((ti, tj))
    return pairs, tags
