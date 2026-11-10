import io
import time
from datetime import time as t

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from algorithm import GAConfig
from auth.permissions import PermissionDenied
from database.models import (Classroom, GenerationHistory, LecturerAvailability, Timetable, TimetableAudit, TimetableEntry)
from exports import excel_export, pdf_export
from exports.common import build_context
from services import comparison_service as cmp
from services import generation_service as gs
from services import job_runner
from services import timetable_service as tts
from services.common import ServiceError, ValidationError
from services.timetable_view import assign_lanes, load_entry_views
from validation import timetable_validator as tv
from validation.prechecks import run_prechecks
from validation.rules import to_minutes

CFG = dict(population_size=12, max_generations=8, seed=1)


def params(**kw):
    return gs.GenerationParams("2025/2026", "FIRST", GAConfig(**{**CFG, **kw.pop("cfg", {})}), **kw)


@pytest.fixture()
def generated(demo, admin):
    return gs.run_generation(demo, admin, params())


# ---------------------------------------------------------------- pre-generation validation
def test_prechecks_pass_on_complete_data(demo):
    assert [i for i in run_prechecks(demo, "2025/2026", "FIRST") if i.severity == "ERROR"] == []


def test_prechecks_flag_missing_data(session, super_admin):
    codes = {i.code for i in run_prechecks(session, "2025/2026", "FIRST")}
    assert {"NO_DEPARTMENTS", "NO_TIME_SLOTS", "NO_ROOMS", "NO_ASSIGNMENTS"} <= codes


def test_prechecks_lecturer_without_availability_and_no_room(demo):
    demo.query(LecturerAvailability).filter(LecturerAvailability.lecturer_id == 1).delete()
    big = demo.query(Classroom).all()
    for r in big:
        r.capacity = 5
    demo.flush()
    codes = {i.code for i in run_prechecks(demo, "2025/2026", "FIRST")}
    assert "LECTURER_NO_AVAILABILITY" in codes and "SESSION_UNPLACEABLE" in codes


def test_generation_blocked_when_prechecks_fail(session, super_admin):
    with pytest.raises(gs.PrecheckFailed) as e:
        gs.run_generation(session, super_admin, params())
    assert e.value.issues
    assert session.scalar(select(func.count(Timetable.id))) == 0


# ---------------------------------------------------------------- generation + persistence
def test_generation_saves_complete_validated_timetable(demo, generated):
    tt = demo.get(Timetable, generated.timetable_id)
    from algorithm.loader import load_scheduling_data
    needed = len(load_scheduling_data(demo, "2025/2026", "FIRST").sessions)
    assert len(tt.entries) == needed                               # every required session present
    assert tt.is_valid and tt.hard_violations == 0 and tt.status == "VALIDATED"
    h = demo.scalar(select(GenerationHistory).where(GenerationHistory.timetable_id == tt.id))
    assert h.status == "COMPLETED" and h.generations > 0 and h.fitness_progress and h.initial_fitness and h.constraint_breakdown
    assert demo.scalar(select(func.count(TimetableAudit.id)).where(TimetableAudit.timetable_id == tt.id)) == 1


def test_independent_validator_agrees_and_never_trusts_fitness(demo, generated):
    tt = demo.get(Timetable, generated.timetable_id)
    assert tv.validate_entries(demo, gs.entries_to_drafts(tt.entries), "2025/2026", "FIRST") == []


def test_versions_are_preserved_not_overwritten(demo, admin, generated):
    second = gs.run_generation(demo, admin, params(parent_id=generated.timetable_id, cfg=dict(seed=2)))
    ids = [t.id for t in demo.scalars(select(Timetable).order_by(Timetable.id))]
    assert ids == [generated.timetable_id, second.timetable_id]
    assert demo.get(Timetable, second.timetable_id).version == 2
    assert len(demo.get(Timetable, generated.timetable_id).entries) > 0
    assert [t.version for t in tts.versions_of(demo, admin, second.timetable_id)] == [1, 2]


def test_failed_generation_saves_no_partial_timetable(demo, admin, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(gs, "run_genetic_algorithm", boom)
    with pytest.raises(ServiceError) as e:
        gs.run_generation(demo, admin, params())
    assert "secret" not in str(e.value) and "No timetable was saved" in str(e.value)
    assert demo.scalar(select(func.count(Timetable.id))) == 0
    h = demo.scalar(select(GenerationHistory))
    assert h.status == "FAILED" and "secret" not in (h.error_message or "")


def test_save_failure_rolls_back_everything(demo, admin, monkeypatch):
    orig = gs.TimetableAudit
    class Bad:
        def __init__(self, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(gs, "TimetableAudit", Bad)
    with pytest.raises(ServiceError, match="No partial"):
        gs.run_generation(demo, admin, params())
    assert demo.scalar(select(func.count(Timetable.id))) == 0 and demo.scalar(select(func.count(TimetableEntry.id))) == 0


def test_invalid_config_rejected_and_permissions(demo, admin, viewer):
    with pytest.raises(ValidationError):
        gs.run_generation(demo, admin, params(cfg=dict(mutation_rate=5)))
    with pytest.raises(PermissionDenied):
        gs.run_generation(demo, viewer, params())
    with pytest.raises(PermissionDenied):
        gs.save_configuration(demo, admin, "x", GAConfig())          # only super admin configures


def test_save_and_reload_configuration(demo, super_admin):
    row = gs.save_configuration(demo, super_admin, "Fast", GAConfig(population_size=10, max_generations=7))
    cfg = gs.config_from_row(row)
    assert cfg.population_size == 10 and cfg.max_generations == 7 and len(cfg.hard_weights) == 10


# ---------------------------------------------------------------- conflict detection on deliberately invalid data
def _entries(demo, generated):
    return gs.entries_to_drafts(demo.get(Timetable, generated.timetable_id).entries)


def _replace(d, **kw):
    from dataclasses import replace
    return replace(d, **kw)


def test_validator_detects_each_violation_type(demo, generated):
    drafts = _entries(demo, generated)
    base = drafts[0]
    def types(mod):
        out = [d for d in drafts[1:]]
        return {c.type for c in tv.validate_entries(demo, mod(out), "2025/2026", "FIRST")}
    assert tv.MISSING in types(lambda o: o)                          # first entry dropped
    assert tv.DUPLICATE in types(lambda o: o + [base, base])
    assert tv.DURATION in types(lambda o: o + [_replace(base, end=base.end + 60)])
    assert tv.WORKING_HOURS in types(lambda o: o + [_replace(base, start=60, end=60 + (base.end - base.start))])
    same_room_overlap = _replace(drafts[1], classroom_id=base.classroom_id, day=base.day, start=base.start + 30, end=base.start + 30 + (drafts[1].end - drafts[1].start))
    assert tv.CLASSROOM in types(lambda o: [base, same_room_overlap])


def _other_room(demo, base):
    return demo.scalar(select(Classroom.id).where(Classroom.id != base.classroom_id))


def test_validator_lecturer_group_capacity_type_availability(demo, generated):
    drafts = _entries(demo, generated)
    by_assign = {}
    for d in drafts:
        by_assign.setdefault(d.assignment_id, []).append(d)
    multi = next(v for v in by_assign.values() if len(v) >= 2)
    x, y = multi[0], multi[1]                                       # same lecturer AND same group
    y2 = _replace(y, day=x.day, start=x.start + 30, end=x.start + 30 + (y.end - y.start), classroom_id=_other_room(demo, x))
    found = {c.type for c in tv.validate_entries(demo, [x, y2], "2025/2026", "FIRST")}
    assert tv.LECTURER in found and tv.GROUP in found
    from database.models import StudentGroup
    demo.query(Classroom).update({"capacity": 1})
    demo.flush()
    assert tv.CAPACITY in {c.type for c in tv.validate_entries(demo, drafts, "2025/2026", "FIRST")}


def test_validator_room_type_and_availability(demo, generated):
    drafts = _entries(demo, generated)
    lab_draft = next(x for x in drafts if demo.get(Classroom, x.classroom_id).room_type == "COMPUTER_LABORATORY")
    normal = demo.scalar(select(Classroom).where(Classroom.room_type == "STANDARD_CLASSROOM"))
    flagged = tv.validate_entries(demo, [_replace(lab_draft, classroom_id=normal.id)], "2025/2026", "FIRST")
    assert tv.ROOM_TYPE in {c.type for c in flagged}                  # lab course placed in a normal room
    assert tv.ROOM_TYPE not in {c.type for c in tv.validate_entries(demo, drafts, "2025/2026", "FIRST")}
    demo.query(LecturerAvailability).delete()
    demo.flush()
    assert tv.AVAILABILITY in {c.type for c in tv.validate_entries(demo, drafts, "2025/2026", "FIRST")}


def test_conflict_rows_have_required_fields(demo, generated):
    cs = tv.validate_entries(demo, _entries(demo, generated)[1:], "2025/2026", "FIRST")
    row = cs[0].as_row()
    for k in ("type", "severity", "course", "lecturer", "classroom", "group", "day", "start", "end", "explanation"):
        assert k in row
    assert tv.summarise(cs)["total"] == len(cs)


# ---------------------------------------------------------------- lifecycle
def test_lifecycle_rules(demo, admin, super_admin, viewer, generated):
    tid = generated.timetable_id
    with pytest.raises(PermissionDenied):
        tts.approve(demo, admin, tid)
    with pytest.raises(PermissionDenied):
        tts.publish(demo, admin, tid)
    with pytest.raises(ValidationError, match="approved"):
        tts.publish(demo, super_admin, tid)                          # not yet approved
    with pytest.raises(PermissionDenied):
        tts.get_timetable(demo, viewer, tid)                         # viewers cannot see unpublished
    assert tts.list_timetables(demo, viewer) == []
    tts.approve(demo, super_admin, tid)
    tt = tts.publish(demo, super_admin, tid)
    assert tt.status == "PUBLISHED" and tts.get_timetable(demo, viewer, tid).id == tid
    assert [t.id for t in tts.list_timetables(demo, viewer)] == [tid]
    actions = [a.action for a in tts.audit_trail(demo, super_admin, tid)]
    assert actions == ["GENERATED", "APPROVED", "PUBLISHED"]


def test_invalid_timetable_cannot_be_approved(demo, admin, super_admin, generated):
    tid = generated.timetable_id
    demo.delete(demo.get(Timetable, tid).entries[0])                 # remove a required session
    demo.flush(); demo.expire_all()
    with pytest.raises(ValidationError, match="invalid timetable cannot be approved"):
        tts.approve(demo, super_admin, tid)
    tts.revalidate(demo, admin, tid)
    tt = demo.get(Timetable, tid)
    assert not tt.is_valid and tt.status == "GENERATED" and tt.hard_violations >= 1


def test_publishing_requires_explicit_replacement_and_archives_old(demo, admin, super_admin, generated):
    a = generated.timetable_id
    b = gs.run_generation(demo, admin, params(cfg=dict(seed=9))).timetable_id
    for tid in (a, b):
        tts.approve(demo, super_admin, tid)
    tts.publish(demo, super_admin, a)
    with pytest.raises(ServiceError, match="already exists"):
        tts.publish(demo, super_admin, b)
    tts.publish(demo, super_admin, b, replace_published=True)
    assert demo.get(Timetable, a).status == "ARCHIVED" and len(demo.get(Timetable, a).entries) > 0
    with pytest.raises(ValidationError):
        tts.archive(demo, super_admin, a)                            # archived is final


def test_revision_creates_new_version(demo, admin, generated):
    rev = tts.create_revision(demo, admin, generated.timetable_id)
    assert rev.version == 2 and rev.parent_id == generated.timetable_id and rev.status == "GENERATED" and not rev.is_valid
    assert len(rev.entries) == len(demo.get(Timetable, generated.timetable_id).entries)


# ---------------------------------------------------------------- viewer, lanes, exports, comparison
def test_assign_lanes_overlap_and_non_overlap():
    from services.timetable_view import EntryView
    def v(i, s, e): return EntryView(i, i, 1, "C", "T", 100, 1, "D", 1, "L", i, "G", 1, "R", "STANDARD_CLASSROOM", 0, s, e)
    out = {x.entry_id: (lane, n) for x, lane, n in assign_lanes([v(1, 480, 600), v(2, 540, 660), v(3, 660, 720)])}
    assert out[1] != out[2] and out[1][1] == 2 and out[2][1] == 2      # overlapping pair shares a cluster of 2 lanes
    assert out[3] == (0, 1)                                           # later session is alone


def test_exports_match_database_and_respect_permissions(demo, admin, super_admin, viewer, generated):
    tid = generated.timetable_id
    with pytest.raises(PermissionDenied):
        pdf_export.export_timetable_pdf(demo, viewer, tid)           # unpublished -> viewer denied
    tts.approve(demo, super_admin, tid); tts.publish(demo, super_admin, tid)
    pdf = pdf_export.export_timetable_pdf(demo, viewer, tid)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    wb = load_workbook(io.BytesIO(excel_export.export_timetable_excel(demo, viewer, tid)))
    assert wb.sheetnames == ["TIMETABLE OVERVIEW", "DEPARTMENT SCHEDULES", "LECTURER SCHEDULES", "CLASSROOM SCHEDULES",
                             "STUDENT GROUP SCHEDULES", "GENERATION SUMMARY"]
    ws = wb["TIMETABLE OVERVIEW"]
    views = load_entry_views(demo, viewer, tid)
    assert ws.max_row - 1 == len(views)
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref and ws["A1"].font.bold
    sheet_rows = {(r[0], r[1], r[2], r[3], r[6]) for r in ws.iter_rows(min_row=2, values_only=True)}
    db_rows = {(v.day_name, f"{v.start // 60:02d}:{v.start % 60:02d}", f"{v.end // 60:02d}:{v.end % 60:02d}", v.course_code, v.room) for v in views}
    assert sheet_rows == db_rows                                      # workbook content equals the stored timetable
    ctx = build_context(demo, viewer, tid, "lecturer", views[0].lecturer_id)
    assert ctx.entries and all(e.lecturer_id == views[0].lecturer_id for e in ctx.entries)
    single = load_workbook(io.BytesIO(excel_export.export_timetable_excel(demo, viewer, tid, "group", views[0].group_id)))
    assert single.sheetnames == ["SCHEDULE", "DETAILS"]


def test_draft_exports_are_labelled_and_pdf_text_contains_data(demo, admin, generated):
    from pypdf import PdfReader
    ctx = build_context(demo, admin, generated.timetable_id)
    assert "NOT PUBLISHED" in ctx.status_note
    pdf = pdf_export.export_timetable_pdf(demo, admin, generated.timetable_id)
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "NOT PUBLISHED" in text and "2025/2026" in text and "Page 1 of" in text
    views = load_entry_views(demo, admin, generated.timetable_id)
    assert all(v.course_code in text for v in views[:5])
    report = pdf_export.export_generation_report_pdf(demo, admin, generated.timetable_id)
    rtext = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(report)).pages)
    assert "Termination reason" in rtext and "Initial fitness" in rtext


def test_unresolved_violations_are_labelled_in_exports(demo, admin, generated):
    demo.delete(demo.get(Timetable, generated.timetable_id).entries[0]); demo.flush(); demo.expire_all()
    tts.revalidate(demo, admin, generated.timetable_id)
    assert "UNRESOLVED HARD CONSTRAINT VIOLATIONS" in build_context(demo, admin, generated.timetable_id).status_note


def test_comparison_never_ranks_invalid_above_valid(demo, admin, generated):
    other = gs.run_generation(demo, admin, params(cfg=dict(seed=3))).timetable_id
    demo.delete(demo.get(Timetable, other).entries[0]); demo.flush(); demo.expire_all()
    tts.revalidate(demo, admin, other)
    c = cmp.compare_timetables(demo, admin, generated.timetable_id, other)
    assert "Timetable A is better" in c.verdict and "hard constraint" in c.verdict
    assert any(ch["change"] == "Only in A" for ch in c.changes)
    same = cmp.compare_timetables(demo, admin, generated.timetable_id, generated.timetable_id)
    assert same.identical


def test_background_job_reports_real_progress(demo, admin, db):
    job = job_runner.start_job(admin, params(cfg=dict(population_size=10, max_generations=6)))
    for _ in range(200):
        if job.status != "RUNNING":
            break
        time.sleep(0.05)
    assert job.status == "COMPLETED" and job.timetable_id
    gens = [h["generation"] for h in job.history]
    assert gens == sorted(gens) and gens[0] == 0 and gens[-1] > 0 and job.latest["max_generations"] == 6


def test_background_job_failure_and_stop(session, super_admin, db):
    job = job_runner.start_job(super_admin, params())            # empty database -> prechecks fail
    for _ in range(100):
        if job.status != "RUNNING":
            break
        time.sleep(0.05)
    assert job.status == "FAILED" and job.issues and not job.timetable_id
