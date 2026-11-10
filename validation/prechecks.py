"""Pre-generation validation of the scheduling dataset."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from algorithm.loader import load_scheduling_data, scope_assignments
from database.models import Classroom, Department, StudentGroup, TimeSlot

ERROR, WARNING = "ERROR", "WARNING"


@dataclass
class Issue:
    severity: str
    code: str
    message: str


def run_prechecks(session: Session, academic_session: str, semester: str, department_id: Optional[int] = None,
                  level: Optional[int] = None, room_ids: Optional[List[int]] = None) -> List[Issue]:
    issues: List[Issue] = []

    def err(code, msg): issues.append(Issue(ERROR, code, msg))
    def warn(code, msg): issues.append(Issue(WARNING, code, msg))

    if not (session.scalar(select(func.count(Department.id)).where(Department.status == "ACTIVE")) or 0):
        err("NO_DEPARTMENTS", "No active departments are registered.")
    if not (session.scalar(select(func.count(TimeSlot.id)).where(TimeSlot.is_active.is_(True))) or 0):
        err("NO_TIME_SLOTS", "No active time slots are defined. Define the teaching hours in SETTINGS.")
    room_q = select(func.count(Classroom.id)).where(Classroom.status == "ACTIVE", Classroom.is_available.is_(True))
    if room_ids is not None:
        room_q = room_q.where(Classroom.id.in_(room_ids or [0]))
    if not (session.scalar(room_q) or 0):
        err("NO_ROOMS", "No active, available classrooms are registered.")
    assignments = scope_assignments(session, academic_session, semester, department_id, level)
    if not assignments:
        err("NO_ASSIGNMENTS", "There are no active course assignments for the selected session, semester and scope.")
        return issues
    # groups in scope that have no assignments
    gq = select(StudentGroup).where(StudentGroup.academic_session == academic_session, StudentGroup.status == "ACTIVE")
    if department_id:
        gq = gq.where(StudentGroup.department_id == department_id)
    if level:
        gq = gq.where(StudentGroup.level == level)
    assigned_groups = {a.group_id for a in assignments}
    for g in session.scalars(gq):
        if g.id not in assigned_groups:
            warn("GROUP_NO_COURSES", f"Student group {g.name} has no course assignments in this semester.")
    data = load_scheduling_data(session, academic_session, semester, department_id, level, room_ids)
    seen = set()
    for a in assignments:
        if not data.lecturer_allowed.get(a.lecturer_id) or not any(data.lecturer_allowed[a.lecturer_id].values()):
            if a.lecturer_id not in seen:
                seen.add(a.lecturer_id)
                err("LECTURER_NO_AVAILABILITY", f"Lecturer {a.lecturer.full_name} has no available scheduling period.")
    for idx, reason in data.unplaceable.items():
        r = data.sessions[idx]
        if r.lecturer_id in seen and "lecturer" in reason.lower():
            continue
        err("SESSION_UNPLACEABLE", f"{r.course_code} session {r.session_no} (group population {r.population}): {reason}")
    # capacity checks (necessary conditions)
    week = {d: sum(e - s for s, e in w) for d, w in data.windows.items()}
    week_total = sum(week.values())
    per_group, per_lec = {}, {}
    for r in data.sessions:
        per_group[r.group_id] = per_group.get(r.group_id, 0) + r.duration
        per_lec[r.lecturer_id] = per_lec.get(r.lecturer_id, 0) + r.duration
    for gid, mins in per_group.items():
        if mins > week_total:
            err("GROUP_OVERLOADED", f"Student group {gid} needs {mins // 60}h of teaching but only {week_total // 60}h exist per week.")
    for lid, mins in per_lec.items():
        if mins > week_total:
            err("LECTURER_OVERLOADED", f"Lecturer {lid} is assigned {mins // 60}h but only {week_total // 60}h exist per week.")
    if data.rooms:
        need = sum(r.duration for r in data.sessions)
        if need > week_total * len(data.rooms):
            err("INSUFFICIENT_CAPACITY", f"Insufficient scheduling capacity: {need // 60}h of sessions but only "
                                         f"{week_total * len(data.rooms) // 60}h of room time per week.")
    return issues


def errors_only(issues: List[Issue]) -> List[Issue]:
    return [i for i in issues if i.severity == ERROR]
