from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from services.timetable_service import get_timetable
from services.timetable_view import EntryView, load_entry_views


@dataclass
class Comparison:
    a_id: int
    b_id: int
    metrics: List[dict]
    changes: List[dict] = field(default_factory=list)
    identical: bool = False
    verdict: str = ""


def compare_timetables(session: Session, actor, a_id: int, b_id: int) -> Comparison:
    require(actor, Permission.GENERATE)
    a, b = get_timetable(session, actor, a_id), get_timetable(session, actor, b_id)
    ea = {(v.assignment_id, v.session_no): v for v in load_entry_views(session, actor, a_id)}
    eb = {(v.assignment_id, v.session_no): v for v in load_entry_views(session, actor, b_id)}

    def row(label, x, y):
        return {"metric": label, "A": x, "B": y}

    metrics = [row("Version", a.version, b.version), row("Status", a.status, b.status),
               row("Independent hard violations", a.hard_violations, b.hard_violations),
               row("Soft penalty", round(a.soft_penalty or 0, 3), round(b.soft_penalty or 0, 3)),
               row("Fitness score", round(a.fitness_score or 0, 6), round(b.fitness_score or 0, 6)),
               row("Scheduled sessions", len(ea), len(eb))]
    changes = []
    for key in sorted(set(ea) | set(eb)):
        x, y = ea.get(key), eb.get(key)
        if x is None or y is None:
            v = x or y
            changes.append({"course": v.course_code, "group": v.group, "session": key[1], "change": "Only in A" if y is None else "Only in B",
                            "A": f"{x.day_name} {x.time_label} {x.room}" if x else "", "B": f"{y.day_name} {y.time_label} {y.room}" if y else ""})
        elif (x.day, x.start, x.end, x.room_id) != (y.day, y.start, y.end, y.room_id):
            what = []
            if (x.day, x.start) != (y.day, y.start):
                what.append("time")
            if x.room_id != y.room_id:
                what.append("classroom")
            changes.append({"course": x.course_code, "group": x.group, "session": key[1], "change": "Moved " + " and ".join(what),
                            "A": f"{x.day_name} {x.time_label} {x.room}", "B": f"{y.day_name} {y.time_label} {y.room}"})
    ha, hb = a.hard_violations or 0, b.hard_violations or 0
    if ha != hb:
        better = "A" if ha < hb else "B"
        verdict = f"Timetable {better} is better: it has fewer hard constraint violations ({min(ha, hb)} versus {max(ha, hb)}). Fitness scores are not compared across different hard violation counts."
    elif ha > 0:
        verdict = "Both timetables contain hard constraint violations. Neither is acceptable; fitness is not used to rank them."
    else:
        sa, sb = a.soft_penalty or 0, b.soft_penalty or 0
        if abs(sa - sb) < 1e-9:
            verdict = "Both timetables are valid with equal soft penalties."
        else:
            verdict = f"Both timetables are valid. Timetable {'A' if sa < sb else 'B'} has the lower soft penalty ({min(sa, sb):.2f} versus {max(sa, sb):.2f})."
    return Comparison(a_id, b_id, metrics, changes, identical=not changes, verdict=verdict)
