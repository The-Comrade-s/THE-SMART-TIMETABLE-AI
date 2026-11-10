"""Tests for the NOUN 2026_2 draft examination timetable import (real PDF)."""
import io
from collections import Counter
from datetime import date, time
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from algorithm import GAConfig
from auth.permissions import PermissionDenied
from database.models import (Classroom, Course, Dataset, DatasetMember, Department, ExamDay, ExamEntry, Lecturer, StudentGroup,
                             TimeSlot, Timetable)
from exports import exam_export
from importers import noun_exam_pdf as nx
from importers.noun_import import DATASET_NAME, build_report
from services import dataset_service as dsv
from services import exam_service as ex
from services import synthetic_service as syn
from services.common import ServiceError, ValidationError

PDF = str(Path(__file__).resolve().parent.parent / "data" / "noun" / "2026_2_E-Exam_Draft_Timetable_57.pdf")


@pytest.fixture(scope="session")
def result():
    return nx.extract_noun_exam_pdf(PDF)


def by_cell(result, day, slot):
    return [e for e in result.entries if e.day_no == day and e.slot == slot]


# ----------------------------------------------------------------------------------------------------- extraction
def test_all_eight_pages_and_sixteen_days_are_processed(result):
    assert (result.pages_total, result.pages_processed, result.page_problems) == (8, 8, {})
    assert [d.day_no for d in result.days] == list(range(1, 17))
    assert Counter(d.page_no for d in result.days) == {1: 1, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 2, 8: 1}


def test_dates_weekdays_and_session_times_are_correct_per_day(result):
    days = {d.day_no: d for d in result.days}
    assert (days[1].exam_date, days[1].weekday) == (date(2026, 11, 18), "Wednesday")
    assert (days[16].exam_date, days[16].weekday) == (date(2026, 12, 7), "Monday")
    for d in result.days:
        assert d.exam_date.strftime("%A") == d.weekday and not d.review
        final = "3pm" if d.day_no in (3, 9, 14) else "2pm"
        assert [s.label for s in d.sessions] == ["8:30am", "11am", final], d.day_no
    assert [s.start for s in days[3].sessions] == [time(8, 30), time(11, 0), time(15, 0)]
    assert [s.start for s in days[1].sessions] == [time(8, 30), time(11, 0), time(14, 0)]


def test_record_counts_match_independent_text_count(result):
    rep = build_report(result)
    assert len(result.entries) == 1063 == result.crosscheck_token_count
    assert rep["independent_count_matches"] and rep["coverage_ok"]
    assert (rep["sessions_identified"], rep["unique_course_codes"]) == (48, 1063)
    assert (rep["batch_a_entries"], rep["batch_b_entries"], rep["noun_prefixed_entries"]) == (20, 20, 181)
    assert (rep["missing_course_codes"], rep["missing_course_titles"], rep["needs_manual_review"]) == (0, 0, 10)
    assert sum(rep["entries_by_page"].values()) == 1063


def test_entries_are_attached_to_the_right_day_and_session(result):
    first = lambda d, s: (by_cell(result, d, s)[0].course_code, by_cell(result, d, s)[0].course_title)
    assert first(1, 1) == ("ARA227", "ARABIC LITERATURE FROM EARLY ISLAM")
    assert first(1, 3)[0] == "CRS111" and first(2, 1)[0] == "PAD251" and first(2, 2)[0] == "ACC206" and first(2, 3)[0] == "HAU105"
    assert first(4, 1)[0] == "ARA118" and first(5, 1)[0] == "BFN209"
    assert first(14, 1)[0] == "NSC214" and first(15, 1)[0] == "ANP201" and first(16, 1)[0] == "EHS206"
    assert any(e.course_code == "CIT237" and e.day_no == 1 and e.slot == 2 for e in result.entries)     # computing course, day 1, 11am


def test_titles_and_codes_are_preserved_exactly_including_source_errors(result):
    titles = {e.course_code: e.course_title for e in result.entries}
    assert titles["ISL231"] == "Intorduction to The Shariah"                       # source typo kept
    assert titles["STT211"] == "Probaility Distribution I"
    assert titles["LIT105"] == "Inttroduction to Prose Literature"
    assert titles["ISL111"] == "Studies On The Qur_an"
    assert titles["KHE107"] == "Skills Development and Techniques in Sports and Ga"       # clipped in the source, not repaired
    assert titles["NOUN-MKT126"] == "Brand Content Management"


def test_noun_prefixed_and_standard_entries_are_never_merged(result):
    codes = {e.course_code: e for e in result.entries}
    for plain, prefixed in (("ECE121", "NOUN-ECE121"), ("COS101", "NOUN-COS101"), ("CIT102", "NOUN-CIT102"), ("PHY101", "NOUN-PHY101")):
        assert plain in codes and prefixed in codes
        assert codes[prefixed].noun_prefixed and not codes[plain].noun_prefixed and codes[prefixed].base_code == plain
    assert codes["NOUN-COS101"].course_title == "Introduction to Computer Science" and codes["NOUN-CSC101"].base_code == "CSC101"
    assert "NOU807-A" in codes and not codes["NOU807-A"].noun_prefixed          # NOU807 is a different, non-prefixed code


def test_batch_a_and_b_remain_distinguishable(result):
    a = {e.course_code for e in result.entries if e.batch == "A"}
    b = {e.course_code for e in result.entries if e.batch == "B"}
    assert "GST102-A" in a and "GST102-B" in b and not a & b
    assert all(e.day_no <= 8 for e in result.entries if e.batch == "A") and all(e.day_no >= 9 for e in result.entries if e.batch == "B")
    assert {e.course_code for e in result.entries if e.noun_prefixed and e.batch == "A"} >= {"NOUN-GST111-A", "NOUN-GST112-A"}


def test_faculty_grouping_comes_from_the_legend(result):
    assert set(result.legend) == {"DAYS_1_8", "DAYS_9_16"}
    assert "FACULY OF COMPUTING" in result.legend["DAYS_1_8"]["text"] and "FACULY OF LAW" in result.legend["DAYS_9_16"]["text"]
    assert result.group_for_day(8) == "DAYS_1_8" and result.group_for_day(9) == "DAYS_9_16"


def test_unclear_records_are_flagged_not_corrected(result):
    flagged = {e.course_code: e for e in result.entries if e.needs_review}
    assert set(flagged) == {"KHE107", "PED112", "KHE204", "FRE241", "ENT102", "ECO154", "HCM244", "ECO103", "HCM231", "ECO153"}
    assert flagged["PED112"].course_title == "Reading In Early Childhood and Prim"


def test_extraction_is_repeatable(result):
    again = nx.extract_noun_exam_pdf(PDF)
    assert [e.record_key(again.source_sha256) for e in again.entries] == [e.record_key(result.source_sha256) for e in result.entries]


def test_source_page_is_recorded_for_every_record(result):
    assert all(1 <= e.page_no <= 8 for e in result.entries)
    assert {e.page_no for e in by_cell(result, 8, 1)} == {5} and {e.page_no for e in by_cell(result, 16, 3)} == {8}


# ----------------------------------------------------------------------------------------------------- import
def counts(s):
    return {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in
            (Department, Lecturer, Course, Classroom, StudentGroup, Timetable, TimeSlot)}


def test_import_stores_everything_and_preserves_existing_data(demo, super_admin, result):
    before = counts(demo)
    out = dsv.import_extraction(demo, super_admin, result)
    assert (out.status, out.imported, out.duplicates_prevented) == ("IMPORTED", 1063, 0)
    ds = demo.get(Dataset, out.dataset_id)
    assert ds.name == DATASET_NAME and ds.is_draft_source and ds.is_test_data and ds.record_count == 1063 and ds.validation_status == "NEEDS_REVIEW"
    assert demo.scalar(select(func.count(ExamEntry.id))) == 1063 and demo.scalar(select(func.count(ExamDay.id))) == 16
    assert counts(demo) == before                                  # nothing existing was touched
    e = demo.scalar(select(ExamEntry).where(ExamEntry.course_code == "NOUN-ECE121"))
    assert e.noun_prefixed and e.page_no == 1 and e.session.day.day_no == 1 and e.session.label_printed == "8:30am"


def test_importing_the_same_pdf_again_creates_no_duplicates(demo, super_admin, result):
    first = dsv.import_extraction(demo, super_admin, result)
    second = dsv.import_extraction(demo, super_admin, result)
    assert (second.status, second.imported, second.duplicates_prevented) == ("ALREADY_IMPORTED", 0, 1063)
    assert second.dataset_id == first.dataset_id
    assert demo.scalar(select(func.count(ExamEntry.id))) == 1063 and demo.scalar(select(func.count(Dataset.id))) == 1


def test_failed_import_leaves_nothing_behind(demo, super_admin, result, monkeypatch):
    orig = dsv.ExamEntry
    calls = {"n": 0}
    class Boom:
        def __init__(self, **kw):
            calls["n"] += 1
            if calls["n"] > 50:
                raise RuntimeError("disk exploded")
            self.o = orig(**kw)
    monkeypatch.setattr(dsv, "ExamEntry", Boom)
    with pytest.raises(ServiceError, match="nothing was saved"):
        dsv.import_extraction(demo, super_admin, result)
    assert demo.scalar(select(func.count(Dataset.id))) == 0 and demo.scalar(select(func.count(ExamDay.id))) == 0


def test_flagged_records_can_be_held_back(demo, super_admin, result):
    out = dsv.import_extraction(demo, super_admin, result, include_review=False)
    assert (out.imported, out.skipped_for_review) == (1053, 10)
    assert demo.scalar(select(func.count(ExamEntry.id))) == 1053


def test_import_permissions(demo, admin, viewer, super_admin, result):
    with pytest.raises(PermissionDenied):
        dsv.import_extraction(demo, viewer, result)
    out = dsv.import_extraction(demo, admin, result)                # admins may import
    with pytest.raises(PermissionDenied):
        dsv.remove_dataset(demo, admin, out.dataset_id)             # only super admins may remove
    with pytest.raises(PermissionDenied):
        ex.search_entries(demo, viewer, out.dataset_id)
    with pytest.raises(ValidationError):
        dsv.import_extraction(demo, admin, nx.ExtractionResult("x.pdf", "0" * 64, 1, 1, {}, [], [], {}, []))


@pytest.fixture()
def imported(demo, super_admin, result):
    return dsv.import_extraction(demo, super_admin, result).dataset_id


def test_revalidation_passes_and_detects_tampering(demo, super_admin, imported):
    rv = dsv.revalidate_dataset(demo, super_admin, imported)
    assert rv["status"] == "NEEDS_REVIEW" and all(c["passed"] for c in rv["checks"])
    demo.scalar(select(ExamEntry).where(ExamEntry.course_code == "ARA227")).course_code = ""
    demo.flush()
    rv = dsv.revalidate_dataset(demo, super_admin, imported)
    assert rv["status"] == "INVALID" and any(not c["passed"] and "course code" in c["check"] for c in rv["checks"])


# ----------------------------------------------------------------------------------------------------- course/timetable views
def test_search_and_filters(demo, super_admin, imported):
    s = lambda **kw: ex.search_entries(demo, super_admin, imported, **kw)
    assert {r.course_code for r in s(text="cit237")} == {"CIT237"}
    assert any("Introduction to Computer Science" in r.course_title for r in s(text="computer science"))
    assert len(s(day_no=1)) == 101 and len(s(day_no=16)) == 58
    assert len(s(batch="A")) == 20 and len(s(batch="B")) == 20 and len(s(batch="NONE")) == 1023
    assert len(s(noun_prefixed=True)) == 181
    assert len(s(session_start=time(15, 0))) == sum(len(s(day_no=d, slot_no=3)) for d in (3, 9, 14))
    assert len(s(faculty_group="DAYS_1_8")) + len(s(faculty_group="DAYS_9_16")) == 1063
    assert len(s(exam_date=date(2026, 11, 18))) == 101 and len(s(needs_review=True)) == 10
    assert s(text="%") == [] and s(text="'; DROP TABLE exam_entries; --") == []
    row = s(text="NOUN-ECE121")[0]
    assert row.noun_prefixed and row.base_code == "ECE121" and row.exam_date == date(2026, 11, 18)


def test_parallel_examinations_are_not_conflicts(demo, super_admin, imported):
    par = ex.parallel_summary(demo, super_admin, imported)
    assert len(par) == 48 and all(p["conflict"] is False for p in par) and max(p["parallel_examinations"] for p in par) > 30
    assert sum(p["parallel_examinations"] for p in par) == 1063


# ----------------------------------------------------------------------------------------------------- synthetic layer + conflicts
@pytest.fixture()
def synthetic(demo, super_admin, imported):
    return syn.build_synthetic_lecture_dataset(demo, super_admin, imported)


def test_synthetic_records_are_clearly_marked(demo, super_admin, synthetic):
    assert synthetic.dataset_type == "SYNTHETIC_LECTURE_TEST" and synthetic.is_test_data
    ids = lambda ent: [m.entity_id for m in demo.scalars(select(DatasetMember).where(DatasetMember.dataset_id == synthetic.id, DatasetMember.entity == ent))]
    assert all("TEST DATA" in l.last_name and l.email.endswith("@synthetic.test") and l.staff_id.startswith("SYN-")
               for l in demo.scalars(select(Lecturer).where(Lecturer.id.in_(ids("lecturer")))))
    assert all(r.name.startswith("SYN ") and "SYNTHETIC" in r.description for r in demo.scalars(select(Classroom).where(Classroom.id.in_(ids("classroom")))))
    assert all("TEST DATA" in g.name for g in demo.scalars(select(StudentGroup).where(StudentGroup.id.in_(ids("student_group")))))
    courses = list(demo.scalars(select(Course).where(Course.id.in_(ids("course")))))
    assert len(courses) == 36 and all(c.code.startswith("SYN-") and "TEST DATA" in c.title for c in courses)
    assert not any(c.code.startswith("SYN-NOUN") for c in courses)
    assert "SYNTHETIC" in demo.scalar(select(Department).where(Department.code == "SYN-CMP")).description


def test_building_the_synthetic_layer_twice_is_refused_and_leaves_exam_data_unchanged(demo, super_admin, imported, synthetic):
    snap = [(e.record_key, e.course_code, e.course_title) for e in demo.scalars(select(ExamEntry).order_by(ExamEntry.id))]
    with pytest.raises(ValidationError, match="already exists"):
        syn.build_synthetic_lecture_dataset(demo, super_admin, imported)
    out = syn.generate_lecture_timetable(demo, super_admin, synthetic, GAConfig(population_size=20, max_generations=15, seed=1))
    assert snap == [(e.record_key, e.course_code, e.course_title) for e in demo.scalars(select(ExamEntry).order_by(ExamEntry.id))]
    assert out.timetable_id


def test_group_conflict_detection_only_flags_the_same_group(demo, super_admin, imported, synthetic):
    ids = [m for m in demo.scalars(select(DatasetMember).where(DatasetMember.dataset_id == synthetic.id, DatasetMember.entity == "course"))]
    from database.models import CourseAssignment
    # pick two synthetic courses whose source examinations share a day and slot, and two that do not
    entry_of = {m.entity_id: int(m.note.split(":")[1]) for m in ids}
    rows = {r.entry_id: r for r in ex.search_entries(demo, super_admin, imported)}
    by_slot = {}
    for cid, eid in entry_of.items():
        by_slot.setdefault(rows[eid].session_key, []).append(cid)
    same = next(v for v in by_slot.values() if len(v) >= 2)[:2]
    diff = [by_slot[k][0] for k in list(by_slot)[:2]]
    g = demo.scalar(select(StudentGroup).order_by(StudentGroup.id))
    lec = demo.scalar(select(Lecturer).order_by(Lecturer.id))
    # rebuild assignments: one dedicated test group registered for exactly the chosen courses
    demo.query(CourseAssignment).filter(CourseAssignment.course_id.in_(entry_of)).delete(synchronize_session=False)
    demo.flush()
    for cid in same:
        c = demo.get(Course, cid)
        g.level = c.level
        demo.add(CourseAssignment(course_id=cid, lecturer_id=lec.id, group_id=g.id, academic_session=g.academic_session, semester="FIRST"))
    demo.flush()
    res = ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id)
    assert len(res["conflicts"]) == 1 and res["conflicts"][0]["group"] == g.name and res["parallel_sessions"] == 48
    demo.query(CourseAssignment).filter(CourseAssignment.course_id.in_(entry_of)).delete(synchronize_session=False)
    for cid in diff:
        demo.add(CourseAssignment(course_id=cid, lecturer_id=lec.id, group_id=g.id, academic_session=g.academic_session, semester="FIRST"))
    demo.flush()
    assert ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id)["conflicts"] == []   # parallel exams of different groups are fine


def test_assumed_duration_turns_adjacent_sessions_into_overlaps(demo, super_admin, imported, synthetic):
    from database.models import CourseAssignment
    ids = {m.entity_id: int(m.note.split(":")[1]) for m in demo.scalars(select(DatasetMember).where(DatasetMember.dataset_id == synthetic.id, DatasetMember.entity == "course"))}
    rows = {r.entry_id: r for r in ex.search_entries(demo, super_admin, imported)}
    pair = None
    for a, ea in ids.items():
        for b, eb in ids.items():
            if a < b and rows[ea].day_no == rows[eb].day_no and {rows[ea].slot_no, rows[eb].slot_no} == {1, 2}:
                pair = (a, b)
    assert pair, "synthetic courses on one day in the 8:30 and 11:00 sessions are needed for this test"
    g = demo.scalar(select(StudentGroup).order_by(StudentGroup.id))
    lec = demo.scalar(select(Lecturer).order_by(Lecturer.id))
    demo.query(CourseAssignment).filter(CourseAssignment.course_id.in_(ids)).delete(synchronize_session=False)
    for cid in pair:
        demo.get(Course, cid).level = g.level
        demo.add(CourseAssignment(course_id=cid, lecturer_id=lec.id, group_id=g.id, academic_session=g.academic_session, semester="FIRST"))
    demo.flush()
    assert ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id)["conflicts"] == []
    assert ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id, 120)["conflicts"] == []         # 8:30 + 2h ends before 11:00
    assert len(ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id, 180)["conflicts"]) == 1     # 3h overlaps 11:00
    with pytest.raises(ValidationError):
        ex.detect_group_conflicts(demo, super_admin, imported, synthetic.id, 5)


# ----------------------------------------------------------------------------------------------------- GA on the synthetic data
def test_genetic_algorithm_on_synthetic_noun_courses(demo, super_admin, admin, imported, synthetic):
    from services import comparison_service as cmp
    from services import timetable_service as tts
    from validation import timetable_validator as tv
    from services.generation_service import entries_to_drafts
    out = syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=40, max_generations=60, seed=1))
    tt = demo.get(Timetable, out.timetable_id)
    assert tt.is_valid and tt.status == "VALIDATED" and tt.hard_violations == 0
    from algorithm.loader import load_scheduling_data
    needed = len(load_scheduling_data(demo, "2026/2027", "FIRST", tt.department_id).sessions)
    assert len(tt.entries) == needed > 36                                            # every required session is scheduled
    assert tv.validate_entries(demo, entries_to_drafts(tt.entries), "2026/2027", "FIRST", tt.department_id) == []     # independent validator
    assert out.result.history[-1]["best_fitness"] >= out.result.history[0]["best_fitness"]
    assert tt.department.code == "SYN-CMP"                                           # lecture scope is the synthetic department only
    second = syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=20, max_generations=20, seed=2), parent_id=tt.id)
    assert demo.get(Timetable, second.timetable_id).version == 2
    assert cmp.compare_timetables(demo, admin, tt.id, second.timetable_id).verdict
    members = {m.entity_id for m in demo.scalars(select(DatasetMember).where(DatasetMember.dataset_id == synthetic.id, DatasetMember.entity == "timetable"))}
    assert members == {tt.id, second.timetable_id}
    tts.approve(demo, super_admin, tt.id)
    tts.publish(demo, super_admin, tt.id)


def test_lecture_timetable_exports(demo, super_admin, admin, imported, synthetic):
    from exports import excel_export, pdf_export
    from pypdf import PdfReader
    out = syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=20, max_generations=10, seed=1))
    pdf = pdf_export.export_timetable_pdf(demo, admin, out.timetable_id)
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "SYN-CIT237" in text and "TEST DATA" in text
    wb = load_workbook(io.BytesIO(excel_export.export_timetable_excel(demo, admin, out.timetable_id)))
    assert wb["TIMETABLE OVERVIEW"].max_row > 36


# ----------------------------------------------------------------------------------------------------- exam exports
def test_exam_exports_contain_the_imported_data(demo, super_admin, imported):
    from pypdf import PdfReader
    pdf = exam_export.export_exam_pdf(demo, super_admin, imported)
    reader = PdfReader(io.BytesIO(pdf))
    text = " ".join(p.extract_text() for p in reader.pages)
    assert "DRAFT SOURCE DATASET" in text and "Day 1: Wednesday, 18 November 2026" in text and "Day 16: Monday, 07 December 2026" in text
    assert "NOUN-ECE121" in text and "Page 1 of" in text and "ARA227" in text
    codes = [c for c in ("CIT237", "NOUN-COS101", "GST102-A", "GST102-B", "NOU807-B") if c in text]
    assert len(codes) == 5
    one = PdfReader(io.BytesIO(exam_export.export_exam_pdf(demo, super_admin, imported, 3)))
    assert " ".join(p.extract_text() for p in one.pages).count("Day 3") >= 1 and len(one.pages) < len(reader.pages)
    wb = load_workbook(io.BytesIO(exam_export.export_exam_excel(demo, super_admin, imported)))
    assert wb.sheetnames == ["ALL ENTRIES", "BY DAY AND SESSION", "VALIDATION REPORT"]
    ws = wb["ALL ENTRIES"]
    assert ws.max_row - 1 == 1063 and ws.freeze_panes == "A2"
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert {r[5] for r in rows} == {e.course_code for e in demo.scalars(select(ExamEntry))}
    assert sum(1 for r in rows if r[8] == "A") == 20 and sum(1 for r in rows if r[9] == "Yes") == 181
    assert wb["BY DAY AND SESSION"].max_row - 1 == 48


# ----------------------------------------------------------------------------------------------------- removal
def test_removing_the_synthetic_dataset_restores_everything_else(demo, super_admin, admin, imported):
    base = counts(demo)                                              # demo institution data, before any synthetic records exist
    synthetic = syn.build_synthetic_lecture_dataset(demo, super_admin, imported)
    assert counts(demo)["courses"] == base["courses"] + 36
    syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=20, max_generations=10, seed=1))
    assert counts(demo)["timetables"] == base["timetables"] + 1
    with pytest.raises(ValidationError, match="Remove the synthetic"):
        dsv.remove_dataset(demo, super_admin, imported)              # the parent cannot go while a child exists
    info = dsv.remove_dataset(demo, super_admin, synthetic.id)
    assert info["timetables"] == 1 and info["course"] == 36 and info["lecturer"] == 9 and info["classroom"] == 9
    assert counts(demo) == base                                      # exactly the original institution data remains
    assert demo.scalar(select(func.count(ExamEntry.id))) == 1063    # examination data untouched
    dsv.remove_dataset(demo, super_admin, imported)
    assert demo.scalar(select(func.count(ExamEntry.id))) == 0 and demo.scalar(select(func.count(Dataset.id))) == 0
    assert counts(demo) == base


def test_removal_is_blocked_for_published_test_timetables(demo, super_admin, admin, imported, synthetic):
    from services import timetable_service as tts
    out = syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=20, max_generations=10, seed=1))
    tts.approve(demo, super_admin, out.timetable_id)
    with pytest.raises(ValidationError, match="approved or published"):
        dsv.remove_dataset(demo, super_admin, synthetic.id)
    assert demo.get(Dataset, synthetic.id) is not None and demo.get(Timetable, out.timetable_id) is not None
    tts.archive(demo, super_admin, out.timetable_id)
    dsv.remove_dataset(demo, super_admin, synthetic.id)


def test_synthetic_lectures_use_only_synthetic_rooms(demo, super_admin, admin, imported, synthetic):
    """The institution's own (here: demo) rooms must never receive synthetic lectures."""
    own_rooms = {r.id for r in demo.scalars(select(Classroom))} - {m.entity_id for m in demo.scalars(select(DatasetMember).where(
        DatasetMember.dataset_id == synthetic.id, DatasetMember.entity == "classroom"))}
    assert own_rooms                                                  # demo rooms exist alongside the synthetic ones
    out = syn.generate_lecture_timetable(demo, admin, synthetic, GAConfig(population_size=20, max_generations=10, seed=1))
    used = {e.classroom_id for e in demo.get(Timetable, out.timetable_id).entries}
    assert used and not used & own_rooms
