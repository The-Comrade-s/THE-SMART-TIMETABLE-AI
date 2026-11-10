"""Loads the scheduling dataset from the database ONCE, then the GA runs fully in memory."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from algorithm.data import RoomInfo, SchedulingData, SessionReq, build_allowed, build_preferred
from algorithm.intervals import merge
from database.models import (Classroom, Course, CourseAssignment, Lecturer, LecturerAvailability, RoomAvailability,
                             StudentGroup, TimeSlot)
from services.course_service import get_course_sessions
from validation.rules import to_minutes


def scope_assignments(session: Session, academic_session: str, semester: str, department_id: Optional[int] = None,
                      level: Optional[int] = None) -> List[CourseAssignment]:
    """Active assignments in scope (all of course, lecturer and group must be active)."""
    q = (select(CourseAssignment).join(Course, Course.id == CourseAssignment.course_id)
         .join(Lecturer, Lecturer.id == CourseAssignment.lecturer_id)
         .join(StudentGroup, StudentGroup.id == CourseAssignment.group_id)
         .where(CourseAssignment.academic_session == academic_session, CourseAssignment.semester == semester,
                CourseAssignment.status == "ACTIVE", Course.status == "ACTIVE", Lecturer.status == "ACTIVE",
                StudentGroup.status == "ACTIVE").order_by(CourseAssignment.id))
    if department_id:
        q = q.where(StudentGroup.department_id == department_id)
    if level:
        q = q.where(StudentGroup.level == level)
    return list(session.scalars(q))


def load_time_windows(session: Session):
    slots = list(session.scalars(select(TimeSlot).where(TimeSlot.is_active.is_(True))))
    windows, starts = {}, {}
    for d in sorted({s.day_of_week for s in slots}):
        ds = [s for s in slots if s.day_of_week == d]
        windows[d] = merge((to_minutes(s.start_time), to_minutes(s.end_time)) for s in ds)
        starts[d] = sorted({to_minutes(s.start_time) for s in ds})
    return windows, starts


def load_scheduling_data(session: Session, academic_session: str, semester: str, department_id: Optional[int] = None,
                         level: Optional[int] = None, room_ids: Optional[List[int]] = None) -> SchedulingData:
    assignments = scope_assignments(session, academic_session, semester, department_id, level)
    sessions: List[SessionReq] = []
    for a in assignments:
        for no, dur in enumerate(get_course_sessions(a.course), start=1):
            sessions.append(SessionReq(len(sessions), a.id, no, a.course_id, a.course.code, a.lecturer_id, a.group_id,
                                       dur, a.course.required_room_type, a.group.population))
    rooms_q = select(Classroom).where(Classroom.status == "ACTIVE", Classroom.is_available.is_(True))
    if room_ids is not None:                      # restrict to a given set of rooms (used to keep synthetic test data apart)
        rooms_q = rooms_q.where(Classroom.id.in_(room_ids or [0]))
    rooms = {r.id: RoomInfo(r.id, f"{r.building} {r.name}", r.capacity, r.room_type) for r in session.scalars(rooms_q)}
    lec_ids = sorted({s.lecturer_id for s in sessions})
    lec_rec = [(r.lecturer_id, r.day_of_week, to_minutes(r.start_time), to_minutes(r.end_time), r.status)
               for r in session.scalars(select(LecturerAvailability).where(LecturerAvailability.lecturer_id.in_(lec_ids or [0])))]
    room_rec = [(r.classroom_id, r.day_of_week, to_minutes(r.start_time), to_minutes(r.end_time), r.status)
                for r in session.scalars(select(RoomAvailability).where(RoomAvailability.classroom_id.in_(list(rooms) or [0])))]
    windows, starts = load_time_windows(session)
    data = SchedulingData(sessions=sessions, rooms=rooms,
                          lecturer_allowed=build_allowed(lec_rec, False, lec_ids),
                          lecturer_preferred=build_preferred(lec_rec, lec_ids),
                          room_allowed=build_allowed(room_rec, True, sorted(rooms)),
                          windows=windows, starts=starts)
    data.build_domains()
    return data
