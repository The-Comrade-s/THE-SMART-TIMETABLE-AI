"""In-memory scheduling dataset. Loaded once before evolution (no database access during the GA)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from algorithm.intervals import Interval, contains, merge, subtract
from database.enums import ROOM_COMPAT

Option = Tuple[int, int, int]  # (room_id, day, start_minute)


@dataclass(frozen=True)
class SessionReq:
    index: int
    assignment_id: int
    session_no: int
    course_id: int
    course_code: str
    lecturer_id: int
    group_id: int
    duration: int
    room_type: str
    population: int


@dataclass(frozen=True)
class RoomInfo:
    id: int
    name: str
    capacity: int
    room_type: str


@dataclass
class SchedulingData:
    sessions: List[SessionReq]
    rooms: Dict[int, RoomInfo]
    lecturer_allowed: Dict[int, Dict[int, List[Interval]]]
    lecturer_preferred: Dict[int, Dict[int, List[Interval]]]
    room_allowed: Dict[int, Dict[int, List[Interval]]]
    windows: Dict[int, List[Interval]]        # permitted teaching windows per day (merged active time slots)
    starts: Dict[int, List[int]]              # permitted start minutes per day
    domains: Dict[int, List[Option]] = field(default_factory=dict)
    domain_sets: Dict[int, frozenset] = field(default_factory=dict)
    unplaceable: Dict[int, str] = field(default_factory=dict)
    blocks: List[List[int]] = field(default_factory=list)   # session indices grouped by assignment

    # ---- static (per-session) constraint predicates -------------------------------------------------
    def lecturer_ok(self, lecturer_id: int, day: int, s: int, e: int) -> bool:
        return contains(self.lecturer_allowed.get(lecturer_id, {}).get(day, []), s, e)

    def room_ok(self, room_id: int, day: int, s: int, e: int) -> bool:
        return contains(self.room_allowed.get(room_id, {}).get(day, []), s, e)

    def in_working_hours(self, day: int, s: int, e: int) -> bool:
        return contains(self.windows.get(day, []), s, e)

    def room_type_ok(self, req: SessionReq, room: RoomInfo) -> bool:
        return room.room_type in ROOM_COMPAT.get(req.room_type, (req.room_type,))

    def static_violations(self, req: SessionReq, room_id: int, day: int, s: int, e: int) -> List[str]:
        out: List[str] = []
        room = self.rooms.get(room_id)
        if not self.lecturer_ok(req.lecturer_id, day, s, e):
            out.append("H4")
        if room is None or not self.room_ok(room_id, day, s, e):
            out.append("H5")
        if room is None or room.capacity < req.population:
            out.append("H6")
        if room is None or not self.room_type_ok(req, room):
            out.append("H7")
        if not self.in_working_hours(day, s, e):
            out.append("H8")
        if e - s != req.duration:
            out.append("H9")
        return out

    # ---- domain construction ------------------------------------------------------------------------
    def build_domains(self) -> None:
        compat: Dict[Tuple[str, int], List[RoomInfo]] = {}
        self.blocks = []
        by_assignment: Dict[int, List[int]] = {}
        for req in self.sessions:
            by_assignment.setdefault(req.assignment_id, []).append(req.index)
            key = (req.room_type, req.population)
            if key not in compat:
                compat[key] = sorted((r for r in self.rooms.values() if r.capacity >= req.population
                                      and self.room_type_ok(req, r)), key=lambda r: (r.capacity, r.id))
            rooms = compat[key]
            options: List[Option] = []
            reason = ""
            if not rooms:
                reason = "No active room has enough capacity and the required room type."
            for day in sorted(self.windows):
                for s in self.starts.get(day, []):
                    e = s + req.duration
                    if not self.in_working_hours(day, s, e) or not self.lecturer_ok(req.lecturer_id, day, s, e):
                        continue
                    for r in rooms:
                        if self.room_ok(r.id, day, s, e):
                            options.append((r.id, day, s))
            if not options and not reason:
                reason = "No time exists where the lecturer, a suitable room and the working hours all coincide."
            self.domains[req.index] = options
            self.domain_sets[req.index] = frozenset(options)
            if reason:
                self.unplaceable[req.index] = reason
        self.blocks = [by_assignment[k] for k in sorted(by_assignment)]


def build_allowed(records: Sequence[Tuple[int, int, int, int, str]], windows_unrestricted: bool,
                  owners: Sequence[int]) -> Dict[int, Dict[int, List[Interval]]]:
    """records: (owner_id, day, start_min, end_min, status).

    Allowed time = (AVAILABLE + PREFERRED intervals) minus UNAVAILABLE intervals.
    Owners with no positive records: unrestricted (whole day) when windows_unrestricted (rooms), otherwise nothing.
    """
    out: Dict[int, Dict[int, List[Interval]]] = {}
    for owner in owners:
        recs = [r for r in records if r[0] == owner]
        days = {r[1] for r in recs} | (set(range(7)) if windows_unrestricted else set())
        per_day: Dict[int, List[Interval]] = {}
        has_positive = any(r[4] in ("AVAILABLE", "PREFERRED") for r in recs)
        for d in days:
            pos = merge((r[2], r[3]) for r in recs if r[1] == d and r[4] in ("AVAILABLE", "PREFERRED"))
            neg = merge((r[2], r[3]) for r in recs if r[1] == d and r[4] == "UNAVAILABLE")
            if not has_positive and windows_unrestricted:
                pos = [(0, 1440)]
            elif windows_unrestricted and not pos:
                pos = []  # room has positive periods on other days only
            per_day[d] = subtract(pos, neg)
        out[owner] = per_day
    return out


def build_preferred(records: Sequence[Tuple[int, int, int, int, str]], owners: Sequence[int]):
    out: Dict[int, Dict[int, List[Interval]]] = {}
    for owner in owners:
        per_day: Dict[int, List[Interval]] = {}
        for d in {r[1] for r in records if r[0] == owner and r[4] == "PREFERRED"}:
            per_day[d] = merge((r[2], r[3]) for r in records if r[0] == owner and r[1] == d and r[4] == "PREFERRED")
        out[owner] = per_day
    return out
