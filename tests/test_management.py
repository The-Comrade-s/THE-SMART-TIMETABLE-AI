from datetime import time

import pytest
from sqlalchemy import select

from auth.permissions import PermissionDenied
from database.models import Course, Department, Lecturer, Timetable
from services import assignment_service as asg
from services import availability_service as av
from services import classroom_service as rooms
from services import course_service as courses
from services import department_service as deps
from services import lecturer_service as lecs
from services import student_group_service as groups
from services.common import ServiceError, ValidationError


@pytest.fixture()
def base(session, super_admin):
    d = deps.create_department(session, super_admin, "Computer Science", "csc", "Science", "d")
    return d


def test_department_crud_search_status_and_detail(session, super_admin, admin, base):
    assert base.code == "CSC"
    with pytest.raises(ValidationError, match="already in use"):
        deps.create_department(session, super_admin, "Other", "CSC")
    with pytest.raises(ValidationError, match="required"):
        deps.create_department(session, super_admin, " ", "X1")
    deps.update_department(session, super_admin, base.id, "Computing", "CSC", "Science", "")
    assert [d.name for d in deps.list_departments(session, admin, "comput")] == ["Computing"]
    assert deps.list_departments(session, admin, "zzz") == []
    deps.set_department_status(session, super_admin, base.id, False)
    assert deps.list_departments(session, admin, status="INACTIVE")[0].id == base.id
    with pytest.raises(ValidationError, match="inactive"):
        lecs.create_lecturer(session, admin, "S1", "A", "B", "a@b.co", "", base.id)


def test_department_delete_blocked_when_referenced(session, super_admin, base):
    lecs.create_lecturer(session, super_admin, "S1", "A", "B", "a@b.co", "", base.id)
    with pytest.raises(ValidationError, match="Deactivate"):
        deps.delete_department(session, super_admin, base.id)
    empty = deps.create_department(session, super_admin, "Empty", "EMP")
    deps.delete_department(session, super_admin, empty.id)


def test_admin_cannot_manage_departments_viewer_cannot_read(session, admin, viewer, base):
    with pytest.raises(PermissionDenied):
        deps.create_department(session, admin, "X", "XX")
    with pytest.raises(PermissionDenied):
        deps.list_departments(session, viewer)
    with pytest.raises(PermissionDenied):
        lecs.create_lecturer(session, viewer, "S9", "A", "B", "q@b.co", "", base.id)
    with pytest.raises(PermissionDenied):
        deps.list_departments(session, None)


def test_lecturer_validation_duplicates_and_search(session, admin, base):
    l = lecs.create_lecturer(session, admin, "s001", "Ada", "Obi", "ADA@Example.com", "0801 234", base.id)
    assert l.staff_id == "S001" and l.email == "ada@example.com"
    with pytest.raises(ValidationError, match="email"):
        lecs.create_lecturer(session, admin, "S002", "X", "Y", "not-an-email", "", base.id)
    with pytest.raises(ValidationError, match="staff ID"):
        lecs.create_lecturer(session, admin, "S001", "X", "Y", "x@y.zz", "", base.id)
    with pytest.raises(ValidationError, match="email address"):
        lecs.create_lecturer(session, admin, "S003", "X", "Y", "ada@example.com", "", base.id)
    with pytest.raises(ValidationError, match="department"):
        lecs.create_lecturer(session, admin, "S004", "X", "Y", "q@y.zz", "", 9999)
    assert len(lecs.list_lecturers(session, admin, "obi")) == 1
    assert lecs.list_lecturers(session, admin, department_id=base.id)[0].id == l.id
    lecs.set_lecturer_status(session, admin, l.id, False)
    assert lecs.list_lecturers(session, admin, status="ACTIVE") == []


def test_search_is_safe_against_wildcards_and_injection(session, admin, base):
    lecs.create_lecturer(session, admin, "S1", "Ada", "Obi", "a@b.co", "", base.id)
    assert lecs.list_lecturers(session, admin, "%") == []
    assert lecs.list_lecturers(session, admin, "'; DROP TABLE lecturers; --") == []
    assert len(lecs.list_lecturers(session, admin)) == 1


def test_availability_overlap_and_validation(session, admin, base):
    l = lecs.create_lecturer(session, admin, "S1", "Ada", "Obi", "a@b.co", "", base.id)
    p = av.add_availability(session, admin, "lecturer", l.id, 0, time(8), time(12))
    with pytest.raises(ValidationError, match="overlaps"):
        av.add_availability(session, admin, "lecturer", l.id, 0, time(11), time(14))
    av.add_availability(session, admin, "lecturer", l.id, 0, time(12), time(14))      # adjacent is fine
    av.add_availability(session, admin, "lecturer", l.id, 1, time(11), time(14))      # other day is fine
    with pytest.raises(ValidationError, match="later"):
        av.add_availability(session, admin, "lecturer", l.id, 2, time(12), time(9))
    with pytest.raises(ValidationError):
        av.add_availability(session, admin, "lecturer", l.id, 9, time(8), time(9))
    av.update_availability(session, admin, "lecturer", p.id, 0, time(8), time(11), "PREFERRED")
    av.remove_availability(session, admin, "lecturer", p.id)
    assert len(av.list_availability(session, admin, "lecturer", l.id)) == 2


def test_course_sessions_and_scheduling_patterns(session, admin, base):
    assert courses.default_session_pattern(180) == [120, 60] and courses.default_session_pattern(60) == [60]
    c = courses.create_course(session, admin, "csc 101", "Intro", 3, base.id, 100, "FIRST", 180)
    assert [s.duration_minutes for s in c.sessions] == [120, 60] and c.code == "CSC101"
    c2 = courses.create_course(session, admin, "CSC102", "Prog Lab", 3, base.id, 100, "FIRST", 180, "COMPUTER_LABORATORY", [60, 60, 60])
    assert len(c2.sessions) == 3 and c2.required_room_type == "COMPUTER_LABORATORY"
    with pytest.raises(ValidationError, match="add up"):
        courses.create_course(session, admin, "CSC103", "Bad", 3, base.id, 100, "FIRST", 180, sessions=[60, 60])
    with pytest.raises(ValidationError, match="already in use"):
        courses.create_course(session, admin, "CSC101", "Dup", 3, base.id, 100, "FIRST", 60)
    with pytest.raises(ValidationError):
        courses.create_course(session, admin, "CSC104", "Lvl", 3, base.id, 150, "FIRST", 60)
    with pytest.raises(ValidationError):
        courses.create_course(session, admin, "CSC105", "Sem", 3, base.id, 100, "THIRD", 60)
    assert len(courses.list_courses(session, admin, level=100, semester="FIRST", department_id=base.id)) == 2
    assert len(courses.list_courses(session, admin, "prog")) == 1
    courses.update_course(session, admin, c.id, "CSC101", "Intro Computing", 3, base.id, 100, "FIRST", 240, "STANDARD_CLASSROOM")
    assert [s.duration_minutes for s in session.get(Course, c.id).sessions] == [120, 120]


def test_classroom_rules(session, admin):
    r = rooms.create_classroom(session, admin, "A1", "Block A", 50, "LECTURE_HALL")
    for cap in (0, -5, "abc"):
        with pytest.raises(ValidationError):
            rooms.create_classroom(session, admin, "A2", "Block A", cap, "LECTURE_HALL")
    with pytest.raises(ValidationError, match="already exists"):
        rooms.create_classroom(session, admin, "a1", "block a", 30, "LECTURE_HALL")
    rooms.create_classroom(session, admin, "A1", "Block B", 30, "SEMINAR_ROOM")           # same name, other building
    rooms.set_classroom_status(session, admin, r.id, False)
    assert [x.id for x in rooms.list_classrooms(session, admin, status="INACTIVE")] == [r.id]
    assert len(rooms.list_classrooms(session, admin, building="Block B", room_type="SEMINAR_ROOM")) == 1
    rooms.update_classroom(session, admin, r.id, "A1", "Block A", 50, "LECTURE_HALL", "", False)
    assert rooms.list_classrooms(session, admin, available=False)[0].id == r.id


def test_student_group_and_assignment_rules(session, admin, base):
    with pytest.raises(ValidationError, match="department"):
        groups.create_group(session, admin, "G", 999, 100, "P", 40, "2025/2026")
    with pytest.raises(ValidationError, match="Academic session"):
        groups.create_group(session, admin, "G", base.id, 100, "P", 40, "2025-26")
    with pytest.raises(ValidationError, match="population"):
        groups.create_group(session, admin, "G", base.id, 100, "P", 0, "2025/2026")
    g = groups.create_group(session, admin, "CSC 100L", base.id, 100, "BSc CS", 60, "2025/2026")
    with pytest.raises(ValidationError, match="already exists"):
        groups.create_group(session, admin, "csc 100l", base.id, 100, "BSc CS", 60, "2025/2026")
    l = lecs.create_lecturer(session, admin, "S1", "Ada", "Obi", "a@b.co", "", base.id)
    c = courses.create_course(session, admin, "CSC101", "Intro", 3, base.id, 100, "FIRST", 120)
    c200 = courses.create_course(session, admin, "CSC201", "Algo", 3, base.id, 200, "FIRST", 120)
    a = asg.create_assignment(session, admin, c.id, l.id, g.id, "2025/2026", "FIRST")
    with pytest.raises(ValidationError, match="already exists"):
        asg.create_assignment(session, admin, c.id, l.id, g.id, "2025/2026", "FIRST")
    with pytest.raises(ValidationError, match="level"):
        asg.create_assignment(session, admin, c200.id, l.id, g.id, "2025/2026", "FIRST")
    with pytest.raises(ValidationError, match="semester"):
        asg.create_assignment(session, admin, c.id, l.id, g.id, "2025/2026", "SECOND")
    l2 = lecs.create_lecturer(session, admin, "S2", "Ben", "Eze", "b@b.co", "", base.id)
    assert asg.create_assignment(session, admin, c.id, l2.id, g.id, "2025/2026", "FIRST")     # team teaching = separate assignment
    lecs.set_lecturer_status(session, admin, l.id, False)
    with pytest.raises(ValidationError, match="inactive"):
        asg.create_assignment(session, admin, c.id, l.id, g.id, "2025/2026", "FIRST")
    assert len(asg.list_assignments(session, admin, course_id=c.id)) == 2
    asg.delete_assignment(session, admin, a.id)


def test_assignment_in_timetable_cannot_be_deleted_and_pattern_locked(demo, admin):
    from algorithm import GAConfig
    from services.generation_service import GenerationParams, run_generation
    out = run_generation(demo, admin, GenerationParams("2025/2026", "FIRST", GAConfig(population_size=8, max_generations=2, seed=1)))
    tt = demo.get(Timetable, out.timetable_id)
    a = tt.entries[0].assignment
    with pytest.raises(ValidationError, match="generated timetables"):
        asg.delete_assignment(demo, admin, a.id)
    c = a.course
    with pytest.raises(ValidationError, match="cannot change"):
        courses.update_course(demo, admin, c.id, c.code, c.title, c.credit_units, c.department_id, c.level, c.semester,
                              c.weekly_minutes + 60, c.required_room_type)
    courses.update_course(demo, admin, c.id, c.code, "Renamed title", c.credit_units, c.department_id, c.level, c.semester,
                          c.weekly_minutes, c.required_room_type)       # cosmetic edits remain possible
