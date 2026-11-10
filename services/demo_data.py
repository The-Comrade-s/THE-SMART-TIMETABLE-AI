"""DEMONSTRATION data generator. Records are clearly marked and never created automatically.

Every demo department code starts with 'DEMO' and its description says it is a demonstration record.
"""
from __future__ import annotations

import random
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (Classroom, Course, CourseAssignment, CourseSession, Department, Lecturer,
                             LecturerAvailability, RoomAvailability, StudentGroup, TimeSlot)
from services.course_service import default_session_pattern
from validation.rules import from_minutes

DEMO_NOTE = "DEMONSTRATION RECORD - not real institutional data"
SIZES = {  # departments, lecturers/dept, courses per group, groups per dept, rooms
    "small": dict(depts=2, lec=4, courses=4, groups=1, rooms=5),
    "medium": dict(depts=3, lec=6, courses=6, groups=2, rooms=9),
    "large": dict(depts=5, lec=8, courses=7, groups=3, rooms=14),
    "tight": dict(depts=3, lec=3, courses=8, groups=3, rooms=5),
}


def has_demo_data(session: Session) -> bool:
    return session.scalar(select(Department.id).where(Department.code.like("DEMO%"))) is not None


def seed_demo(session: Session, size: str = "small", academic_session: str = "2025/2026", seed: int = 7,
              semester: str = "FIRST") -> dict:
    cfg = SIZES[size]
    rng = random.Random(seed)
    if session.scalar(select(TimeSlot.id)) is None:
        for d in range(5):
            for h in range(8, 18):
                session.add(TimeSlot(day_of_week=d, start_time=time(h), end_time=time(h + 1), duration_minutes=60, is_active=True))
    rooms = []
    types = ["STANDARD_CLASSROOM"] * 4 + ["LECTURE_HALL"] * 2 + ["COMPUTER_LABORATORY"] * 2 + ["SCIENCE_LABORATORY"]
    for i in range(cfg["rooms"]):
        t = types[i % len(types)] if i >= 3 else ["LECTURE_HALL", "COMPUTER_LABORATORY", "SCIENCE_LABORATORY"][i]
        cap = {"LECTURE_HALL": 200, "COMPUTER_LABORATORY": 80, "SCIENCE_LABORATORY": 80}.get(t, rng.choice([60, 80, 100]))
        room = Classroom(name=f"DEMO-R{i + 1:02d}", building=f"DEMO Block {chr(65 + i % 3)}", capacity=cap, room_type=t,
                         description=DEMO_NOTE)
        session.add(room)
        rooms.append(room)
    session.flush()
    for r in rooms[: max(1, len(rooms) // 3)]:   # a few rooms have explicit availability, the rest are open
        for d in range(5):
            session.add(RoomAvailability(classroom_id=r.id, day_of_week=d, start_time=time(8), end_time=time(18), status="AVAILABLE"))
    n_course = 0
    for di in range(cfg["depts"]):
        dep = Department(name=f"Demo Department {di + 1}", code=f"DEMO{di + 1}", faculty="Demo Faculty", description=DEMO_NOTE)
        session.add(dep)
        session.flush()
        lecturers = []
        for li in range(cfg["lec"]):
            lec = Lecturer(staff_id=f"DEMO-{di + 1}{li + 1:02d}", first_name=f"Demo{li + 1}", last_name=f"Lecturer{di + 1}",
                           email=f"demo.lecturer.{di + 1}.{li + 1}@example.test", phone="0800000000", department_id=dep.id,
                           employment_status="FULL_TIME")
            session.add(lec)
            lecturers.append(lec)
        session.flush()
        for lec in lecturers:
            for d in range(5):
                status = "PREFERRED" if (d in (0, 2) and rng.random() < 0.4) else "AVAILABLE"
                session.add(LecturerAvailability(lecturer_id=lec.id, day_of_week=d, start_time=time(8), end_time=time(18), status=status))
        for gi in range(cfg["groups"]):
            level = 100 * (gi + 1)
            grp = StudentGroup(name=f"DEMO {dep.code} {level}L", department_id=dep.id, level=level, programme=f"Demo Programme {di + 1}",
                               population=rng.choice([35, 45, 55, 70]), academic_session=academic_session)
            session.add(grp)
            session.flush()
            for ci in range(cfg["courses"]):
                n_course += 1
                hours = rng.choice([1, 2, 2, 3, 3])
                rtype = "COMPUTER_LABORATORY" if ci == 0 else ("SCIENCE_LABORATORY" if ci == 1 and di % 2 else "STANDARD_CLASSROOM")
                course = Course(code=f"DEMO{di + 1}{level // 100}{ci + 1:02d}", title=f"Demo Course {di + 1}-{level}-{ci + 1}",
                                credit_units=hours, department_id=dep.id, level=level, semester=semester,
                                weekly_minutes=hours * 60, required_room_type=rtype)
                course.sessions = [CourseSession(session_no=i + 1, duration_minutes=m) for i, m in enumerate(default_session_pattern(hours * 60))]
                session.add(course)
                session.flush()
                session.add(CourseAssignment(course_id=course.id, lecturer_id=rng.choice(lecturers).id, group_id=grp.id,
                                             academic_session=academic_session, semester=semester))
    session.flush()
    return {"departments": cfg["depts"], "rooms": cfg["rooms"], "courses": n_course}
