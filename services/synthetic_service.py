"""SYNTHETIC lecture-timetable test layer built on top of an imported examination dataset.

Everything created here is invented test data and is marked as such (names, codes, e-mails, descriptions). The examination
records are only used as the list of courses; they are never modified, and examination slots are never used as lecture slots.
"""
from __future__ import annotations

import random
import re
from datetime import time
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import (Classroom, Course, CourseAssignment, CourseSession, Dataset, DatasetMember, Department, ExamEntry,
                             Lecturer, LecturerAvailability, RoomAvailability, StudentGroup, TimeSlot)
from services.common import ValidationError, utcnow
from services.course_service import default_session_pattern

TEST_TAG = "TEST DATA"
SYN_NOTE = "SYNTHETIC TEST DATA - not NOUN institutional information"
DEFAULT_PREFIXES = ("CIT", "COS", "CSC", "CYB", "IFT", "INS", "CSO")     # INFERRED from the code prefix, not stated in the PDF
LAB_WORDS = ("laboratory", "practical")
STREAM_SIZE = 8
ACADEMIC_SESSION = "2026/2027"
SEMESTER = "FIRST"
SYNTHETIC_DATASET_NAME = "NOUN 2026_2 COMPUTING COURSES \u2014 SYNTHETIC LECTURE TEST DATA"


def _member(session: Session, ds: Dataset, entity: str, obj, note: Optional[str] = None) -> None:
    session.add(DatasetMember(dataset_id=ds.id, entity=entity, entity_id=obj.id, note=note))


def build_synthetic_lecture_dataset(session: Session, actor, exam_dataset_id: int, prefixes: Sequence[str] = DEFAULT_PREFIXES,
                                    seed: int = 2026) -> Dataset:
    require(actor, Permission.IMPORT_DATASETS)
    src = session.get(Dataset, exam_dataset_id)
    if src is None or src.dataset_type != "EXAM_TIMETABLE_SOURCE":
        raise ValidationError("Select an imported examination dataset first.")
    if session.scalar(select(Dataset.id).where(Dataset.parent_dataset_id == src.id, Dataset.dataset_type == "SYNTHETIC_LECTURE_TEST")):
        raise ValidationError("A synthetic lecture dataset already exists for this examination dataset. Remove it first to rebuild.")
    rng = random.Random(seed)
    pattern = re.compile(r"^(?:%s)(\d)\d\d$" % "|".join(re.escape(p) for p in prefixes))
    picked: Dict[str, ExamEntry] = {}
    for e in session.scalars(select(ExamEntry).where(ExamEntry.dataset_id == src.id).order_by(ExamEntry.id)):
        if e.noun_prefixed or e.batch or not e.course_title or e.course_code in picked:
            continue
        m = pattern.match(e.course_code)
        if m and 1 <= int(m.group(1)) <= 6:
            picked[e.course_code] = e
    if not picked:
        raise ValidationError("No courses with the selected code prefixes were found in the examination dataset.")
    with session.begin_nested():
        ds = Dataset(name=SYNTHETIC_DATASET_NAME, dataset_type="SYNTHETIC_LECTURE_TEST", source_document=src.source_document,
                     is_draft_source=False, is_test_data=True, parent_dataset_id=src.id, import_status="IMPORTED",
                     validation_status="NOT_VALIDATED", imported_by=getattr(actor, "id", None), validated_at=None,
                     notes=("SYNTHETIC lecture-timetable test layer. Course codes and titles come from the draft examination "
                            "timetable; every lecturer, room, student group, population, availability and teaching requirement was "
                            "invented for testing and is not NOUN information. Course discipline is inferred from the code prefix."))
        session.add(ds)
        session.flush()
        dep = Department(name=f"Synthetic Computing Courses ({TEST_TAG})", code="SYN-CMP", faculty="SYNTHETIC",
                         description=SYN_NOTE)
        session.add(dep)
        session.flush()
        _member(session, ds, "department", dep)
        # teaching hours: only created when the institution has none, so existing settings are never changed
        if session.scalar(select(func.count(TimeSlot.id))) == 0:
            for d in range(5):
                for h in range(8, 18):
                    slot = TimeSlot(day_of_week=d, start_time=time(h), end_time=time(h + 1), duration_minutes=60, is_active=True)
                    session.add(slot)
                    session.flush()
                    _member(session, ds, "time_slot", slot, SYN_NOTE)
        # rooms
        room_specs = [("Hall A", "LECTURE_HALL", 200), ("Hall B", "LECTURE_HALL", 150), ("Room 1", "STANDARD_CLASSROOM", 100),
                      ("Room 2", "STANDARD_CLASSROOM", 100), ("Room 3", "STANDARD_CLASSROOM", 80), ("Seminar 1", "SEMINAR_ROOM", 60),
                      ("Lab 1", "COMPUTER_LABORATORY", 90), ("Lab 2", "COMPUTER_LABORATORY", 90), ("Lab 3", "COMPUTER_LABORATORY", 60)]
        rooms = []
        for name, rtype, cap in room_specs:
            r = Classroom(name=f"SYN {name}", building="SYN Test Block", capacity=cap, room_type=rtype, description=SYN_NOTE)
            session.add(r)
            session.flush()
            _member(session, ds, "classroom", r)
            rooms.append(r)
        lab = next(r for r in rooms if r.name == "SYN Lab 3")
        session.add(RoomAvailability(classroom_id=lab.id, day_of_week=4, start_time=time(14), end_time=time(18), status="UNAVAILABLE"))
        # lecturers
        n_lec = max(4, -(-len(picked) // 4))
        lecturers: List[Lecturer] = []
        for i in range(1, n_lec + 1):
            lec = Lecturer(staff_id=f"SYN-L{i:02d}", first_name="Synthetic", last_name=f"Lecturer {i:02d} ({TEST_TAG})",
                           email=f"synthetic.lecturer{i:02d}@synthetic.test", phone=None, department_id=dep.id,
                           employment_status="FULL_TIME")
            session.add(lec)
            session.flush()
            _member(session, ds, "lecturer", lec)
            lecturers.append(lec)
            short_day = rng.randrange(5)
            for d in range(5):
                if d == short_day:
                    session.add(LecturerAvailability(lecturer_id=lec.id, day_of_week=d, start_time=time(8), end_time=time(13), status="AVAILABLE"))
                    continue
                session.add(LecturerAvailability(lecturer_id=lec.id, day_of_week=d, start_time=time(8), end_time=time(9), status="AVAILABLE"))
                session.add(LecturerAvailability(lecturer_id=lec.id, day_of_week=d, start_time=time(9), end_time=time(12),
                                                 status="PREFERRED" if rng.random() < 0.5 else "AVAILABLE"))
                session.add(LecturerAvailability(lecturer_id=lec.id, day_of_week=d, start_time=time(12), end_time=time(18), status="AVAILABLE"))
        # student groups: each level is split into streams of at most STREAM_SIZE courses so no group has an impossible timetable
        stream_of: Dict[str, StudentGroup] = {}
        levels = sorted({int(pattern.match(c).group(1)) * 100 for c in picked})
        n_groups = 0
        for lv in levels:
            codes = sorted(c for c in picked if int(pattern.match(c).group(1)) * 100 == lv)
            for idx in range(0, len(codes), STREAM_SIZE):
                chunk = codes[idx:idx + STREAM_SIZE]
                n = idx // STREAM_SIZE + 1
                g = StudentGroup(name=f"SYN Computing {lv}L Stream {n} ({TEST_TAG})", department_id=dep.id, level=lv,
                                 programme="Synthetic Computing Programme", population=rng.choice([45, 55, 65, 75]),
                                 academic_session=ACADEMIC_SESSION)
                session.add(g)
                session.flush()
                _member(session, ds, "student_group", g)
                n_groups += 1
                for c in chunk:
                    stream_of[c] = g
        # courses and assignments (one lecturer per course, balanced by load)
        load = {l.id: 0 for l in lecturers}
        for code in sorted(picked):
            e = picked[code]
            lv = int(pattern.match(code).group(1)) * 100
            hours = rng.choice([2, 3])
            is_lab = any(w in e.course_title.lower() for w in LAB_WORDS)
            course = Course(code=f"SYN-{code}"[:20], title=f"{e.course_title} ({TEST_TAG})"[:200], credit_units=hours, department_id=dep.id,
                            level=lv, semester=SEMESTER, weekly_minutes=hours * 60,
                            required_room_type="COMPUTER_LABORATORY" if is_lab else "STANDARD_CLASSROOM")
            course.sessions = [CourseSession(session_no=i + 1, duration_minutes=m) for i, m in enumerate(default_session_pattern(hours * 60))]
            session.add(course)
            session.flush()
            _member(session, ds, "course", course, f"source_exam_entry:{e.id}")
            lec_id = min(load, key=lambda k: (load[k], k))
            load[lec_id] += hours
            a = CourseAssignment(course_id=course.id, lecturer_id=lec_id, group_id=stream_of[code].id, academic_session=ACADEMIC_SESSION,
                                 semester=SEMESTER)
            session.add(a)
            session.flush()
            _member(session, ds, "course_assignment", a)
        ds.record_count = len(picked)
        ds.report = {"courses": len(picked), "lecturers": len(lecturers), "rooms": len(rooms), "groups": n_groups, "stream_size": STREAM_SIZE,
                     "levels": levels, "prefixes": list(prefixes), "seed": seed, "academic_session": ACADEMIC_SESSION,
                     "semester": SEMESTER, "department_code": "SYN-CMP", "marker": SYN_NOTE,
                     "excluded": "NOUN-prefixed and Batch A/B entries are not used; discipline is inferred from the code prefix",
                     "created_at": utcnow().isoformat()}
        session.flush()
    return ds


def synthetic_dataset_for(session: Session, exam_dataset_id: int) -> Optional[Dataset]:
    return session.scalar(select(Dataset).where(Dataset.parent_dataset_id == exam_dataset_id,
                                                Dataset.dataset_type == "SYNTHETIC_LECTURE_TEST"))


def register_timetable(session: Session, ds: Dataset, timetable_id: int) -> None:
    if not session.scalar(select(DatasetMember.id).where(DatasetMember.dataset_id == ds.id, DatasetMember.entity == "timetable",
                                                         DatasetMember.entity_id == timetable_id)):
        session.add(DatasetMember(dataset_id=ds.id, entity="timetable", entity_id=timetable_id, note="generated from synthetic data"))
        session.flush()


def department_id_of(session: Session, ds: Dataset) -> int:
    ids = list(session.scalars(select(DatasetMember.entity_id).where(DatasetMember.dataset_id == ds.id, DatasetMember.entity == "department")))
    if not ids:
        raise ValidationError("The synthetic dataset has no department.")
    return ids[0]


def generate_lecture_timetable(session: Session, actor, ds: Dataset, config, parent_id: Optional[int] = None, name: str = ""):
    """Run the existing Genetic Algorithm workflow on the synthetic lecture data only (department scope SYN-CMP)."""
    from services.generation_service import GenerationParams, run_generation
    require(actor, Permission.GENERATE)
    require(actor, Permission.IMPORT_DATASETS)
    if ds.dataset_type != "SYNTHETIC_LECTURE_TEST":
        raise ValidationError("Lecture timetables can only be generated from a synthetic lecture dataset.")
    dep_id = department_id_of(session, ds)
    rooms = list(session.scalars(select(DatasetMember.entity_id).where(DatasetMember.dataset_id == ds.id, DatasetMember.entity == "classroom")))
    params = GenerationParams(ACADEMIC_SESSION, SEMESTER, config, department_id=dep_id, name=name, parent_id=parent_id, room_ids=rooms)
    outcome = run_generation(session, actor, params)
    register_timetable(session, ds, outcome.timetable_id)
    session.commit()
    return outcome
