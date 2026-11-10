"""Flat, display-ready entry records joined from the database (used by viewer, PDF, Excel, comparison)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.enums import DAYS
from services.timetable_service import get_timetable
from validation.rules import fmt_time, to_minutes


@dataclass(frozen=True)
class EntryView:
    entry_id: int
    assignment_id: int
    session_no: int
    course_code: str
    course_title: str
    level: int
    department_id: int
    department: str
    lecturer_id: int
    lecturer: str
    group_id: int
    group: str
    room_id: int
    room: str
    room_type: str
    day: int
    start: int
    end: int

    @property
    def day_name(self) -> str:
        return DAYS[self.day]

    @property
    def time_label(self) -> str:
        return f"{self.start // 60:02d}:{self.start % 60:02d} - {self.end // 60:02d}:{self.end % 60:02d}"


def load_entry_views(session: Session, actor, timetable_id: int, department_id: Optional[int] = None,
                     level: Optional[int] = None, group_id: Optional[int] = None, lecturer_id: Optional[int] = None,
                     room_id: Optional[int] = None, day: Optional[int] = None) -> List[EntryView]:
    tt = get_timetable(session, actor, timetable_id)    # enforces who may see it
    out: List[EntryView] = []
    for e in tt.entries:
        a = e.assignment
        v = EntryView(e.id, a.id, e.session_no, a.course.code, a.course.title, a.group.level, a.group.department_id,
                      a.group.department.name, a.lecturer_id, a.lecturer.full_name, a.group_id, a.group.name, e.classroom_id,
                      f"{e.classroom.building} {e.classroom.name}", e.classroom.room_type, e.day_of_week,
                      to_minutes(e.start_time), to_minutes(e.end_time))
        if ((department_id is None or v.department_id == department_id) and (level is None or v.level == level)
                and (group_id is None or v.group_id == group_id) and (lecturer_id is None or v.lecturer_id == lecturer_id)
                and (room_id is None or v.room_id == room_id) and (day is None or v.day == day)):
            out.append(v)
    out.sort(key=lambda v: (v.day, v.start, v.group, v.course_code))
    return out


def assign_lanes(views: List[EntryView]):
    """Greedy interval colouring so overlapping blocks of one day sit side by side. Returns [(view, lane, lanes_in_cluster)]."""
    result = []
    for day in sorted({v.day for v in views}):
        items = sorted([v for v in views if v.day == day], key=lambda v: (v.start, v.end))
        cluster: List[tuple] = []
        lane_end: List[int] = []
        def flush():
            n = max((l for _, l in cluster), default=-1) + 1
            result.extend((v, l, n) for v, l in cluster)
        for v in items:
            if cluster and v.start >= max(lane_end):
                flush()
                cluster, lane_end = [], []
            for l, end in enumerate(lane_end):
                if end <= v.start:
                    lane_end[l] = v.end
                    cluster.append((v, l))
                    break
            else:
                lane_end.append(v.end)
                cluster.append((v, len(lane_end) - 1))
        if cluster:
            flush()
    return result
