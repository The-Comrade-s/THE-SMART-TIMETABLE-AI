import os
from datetime import time

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from database import health_check, session_scope
from database.models import (AlgorithmConfiguration, Classroom, Course, CourseAssignment, Department, Lecturer,
                             LecturerAvailability, StudentGroup, TimeSlot, Timetable, TimetableEntry, User)


def _dep(s, code="CSC"):
    d = Department(name="Computer Science", code=code)
    s.add(d); s.flush()
    return d


def test_health_check_and_migration_version(db):
    assert health_check()[0] == "ok"
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from database import get_engine
    root = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head == "0002"
    with get_engine().connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == head


def test_all_expected_tables_created(db):
    from database import get_engine
    names = set(inspect(get_engine()).get_table_names())
    assert {"departments", "lecturers", "courses", "classrooms", "student_groups", "course_assignments", "lecturer_availability",
            "room_availability", "time_slots", "timetables", "timetable_entries", "algorithm_configurations", "generation_history",
            "users", "user_sessions", "course_sessions", "timetable_audit", "app_settings", "datasets", "dataset_members", "exam_days",
            "exam_sessions", "exam_entries"} <= names


def test_unique_constraints(session):
    d = _dep(session)
    with pytest.raises(IntegrityError):
        session.add(Department(name="Other", code="CSC")); session.flush()
    session.rollback()


def test_foreign_keys_enforced_and_restrict(session):
    d = _dep(session)
    lec = Lecturer(staff_id="S1", first_name="A", last_name="B", email="a@b.co", department_id=d.id)
    session.add(lec); session.commit()
    with pytest.raises(IntegrityError):
        session.delete(d); session.flush()
    session.rollback()
    with pytest.raises(IntegrityError):
        session.add(Lecturer(staff_id="S2", first_name="A", last_name="B", email="x@b.co", department_id=9999)); session.flush()
    session.rollback()


@pytest.mark.parametrize("make", [
    lambda d: Classroom(name="X", building="B", capacity=0, room_type="STANDARD_CLASSROOM"),
    lambda d: Classroom(name="X", building="B", capacity=10, room_type="NOT_A_TYPE"),
    lambda d: TimeSlot(day_of_week=0, start_time=time(10), end_time=time(9), duration_minutes=60),
    lambda d: LecturerAvailability(lecturer_id=1, day_of_week=0, start_time=time(10), end_time=time(10)),
    lambda d: Course(code="C1", title="T", credit_units=3, department_id=d.id, level=150, semester="FIRST", weekly_minutes=60),
    lambda d: StudentGroup(name="G", department_id=d.id, level=100, programme="P", population=0, academic_session="2025/2026"),
    lambda d: AlgorithmConfiguration(population_size=10, max_generations=5, mutation_rate=2.0, crossover_rate=0.5, elite_size=1),
    lambda d: User(full_name="X", email="x@y.zz", password_hash="h", role="HACKER"),
])
def test_check_constraints_reject_invalid_rows(session, make):
    d = _dep(session)
    lec = Lecturer(staff_id="S1", first_name="A", last_name="B", email="a@b.co", department_id=d.id); session.add(lec); session.flush()
    with pytest.raises(IntegrityError):
        session.add(make(d)); session.flush()
    session.rollback()


def test_session_scope_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with session_scope() as s:
            s.add(Department(name="Temp", code="TMP")); s.flush()
            raise RuntimeError("boom")
    with session_scope() as s:
        assert s.scalar(select(Department).where(Department.code == "TMP")) is None


def test_historical_timetable_records_are_protected(demo, admin):
    from services.generation_service import GenerationParams, run_generation
    from algorithm import GAConfig
    out = run_generation(demo, admin, GenerationParams("2025/2026", "FIRST", GAConfig(population_size=8, max_generations=3, seed=1)))
    tt = demo.get(Timetable, out.timetable_id)
    entry = tt.entries[0]
    room_id, assign_id = entry.classroom_id, entry.course_assignment_id
    for model, pk in ((Classroom, room_id), (CourseAssignment, assign_id), (Timetable, tt.id)):
        with pytest.raises(IntegrityError):
            demo.delete(demo.get(model, pk)); demo.flush()
        demo.rollback()
    assert demo.get(Timetable, out.timetable_id) is not None
