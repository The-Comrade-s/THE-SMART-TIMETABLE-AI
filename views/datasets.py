"""Dataset management (inside SETTINGS): import, inspect, validate, test and remove datasets."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st
from sqlalchemy import select

from algorithm import GAConfig
from auth.permissions import Permission, has_permission
from database import session_scope
from database.models import Dataset, DatasetMember, Timetable
from exports import exam_export
from importers import noun_exam_pdf as extractor
from services import comparison_service as cmp
from services import dataset_service as dsv
from services import exam_service as ex
from services import synthetic_service as syn
from services.common import ServiceError
from ui.components import empty_state, metric_card, notice, page_header, section_head
from ui.crud import attempt, confirm_button
from ui.navigation import go
from ui.state import flash
from ui.tables import Badge, paginated_table, status_badge

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "noun"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
STATUS_KIND = {"VALID": "ok", "NEEDS_REVIEW": "sample", "INVALID": "error", "NOT_VALIDATED": "muted", "IMPORTED": "ok", "FAILED": "error"}
TYPE_LABEL = {"EXAM_TIMETABLE_SOURCE": "Examination timetable (draft source)", "SYNTHETIC_LECTURE_TEST": "Synthetic lecture test data"}


def render() -> None:
    user = st.session_state["user"]
    with session_scope() as s:
        datasets = dsv.list_datasets(s, user)
    section_head("Datasets", "Test data", "sample")
    notice("info", "Datasets hold imported or synthetic test data. They never replace or change your institution's own records.", "Note")
    paginated_table("ds_list", ["Dataset", "Source document", "Imported", "Type", "Records", "Import status", "Validation"],
                    [[d.name, d.source_document or "", d.imported_at.strftime("%Y-%m-%d %H:%M"), TYPE_LABEL[d.dataset_type], d.record_count,
                      Badge(d.import_status.title(), STATUS_KIND[d.import_status]),
                      Badge(d.validation_status.replace("_", " ").title(), STATUS_KIND[d.validation_status])] for d in datasets],
                    page_size=6, empty_title="No datasets yet", empty_body="Import the examination timetable PDF below.")
    if datasets:
        pick = st.selectbox("Dataset", [d.id for d in datasets], key="ds_pick", format_func=lambda i: next(d.name for d in datasets if d.id == i))
        cur = next(d for d in datasets if d.id == pick)
        c1, c2, c3 = st.columns(3)
        if c1.button("View dataset", key="ds_view", type="primary", width="stretch"):
            st.session_state["ds_open"] = pick
        if c2.button("Revalidate dataset", key="ds_reval", width="stretch"):
            if attempt(lambda s: dsv.revalidate_dataset(s, user, pick), "Dataset revalidated."):
                st.session_state["ds_open"] = pick
                st.rerun()
        with c3:
            if has_permission(user, Permission.REMOVE_DATASETS):
                def remove():
                    try:
                        with session_scope() as s:
                            info = dsv.remove_dataset(s, user, pick)
                        st.session_state.pop("ds_open", None)
                        flash("success", f"Test dataset removed ({sum(v for v in info.values() if isinstance(v, int))} records). Other data was not touched.")
                    except Exception as exc:  # noqa: BLE001
                        flash("error", str(exc) if isinstance(exc, ServiceError) else "The dataset could not be removed.")
                confirm_button("Remove test dataset", f"Remove '{cur.name}' and every record it created? Records from any other source are not touched. This cannot be undone.",
                               remove, f"ds_rm_{pick}")
    with st.expander("Import the examination timetable PDF", expanded=not datasets):
        _import_section(user)
    opened = st.session_state.get("ds_open")
    if opened and any(d.id == opened for d in datasets):
        d = next(x for x in datasets if x.id == opened)
        section_head(d.name)
        if d.is_draft_source:
            notice("warning", "The source document is labelled DRAFT. This is a draft source dataset for testing, not an approved or final timetable.", "Draft")
        if d.dataset_type == "EXAM_TIMETABLE_SOURCE":
            _exam_detail(user, d)
        else:
            _synthetic_detail(user, d)


# ----------------------------------------------------------------------------------------------------- import
def _import_section(user) -> None:
    files = sorted(p.name for p in DATA_DIR.glob("*.pdf")) if DATA_DIR.exists() else []
    mode = st.radio("Source", ["Bundled file", "Upload a PDF"], horizontal=True, key="imp_mode")
    path, label = None, ""
    if mode == "Bundled file":
        if files:
            label = st.selectbox("Document", files, key="imp_file")
            path = str(DATA_DIR / label)
        else:
            st.caption("No PDF files are bundled with the application.")
    else:
        up = st.file_uploader("PDF document", type=["pdf"], key="imp_upload")
        if up is not None:
            data = up.getvalue()
            if len(data) > MAX_UPLOAD_BYTES:
                notice("error", "The file is larger than 25 MB.")
            elif not data.startswith(b"%PDF"):
                notice("error", "The selected file is not a PDF document.")
            else:
                tmp = Path(tempfile.gettempdir()) / f"upload_{abs(hash(up.name)) % 10**8}_{up.name.replace('/', '_')}"
                tmp.write_bytes(data)
                path, label = str(tmp), up.name
    if st.button("Start extraction", key="imp_start", type="primary", disabled=path is None):
        bar, msg = st.progress(0.0), st.empty()
        def prog(done, total, text):
            bar.progress(min(1.0, done / max(1, total)))
            msg.caption(text)
        try:
            st.session_state["imp_result"] = extractor.extract_noun_exam_pdf(path, prog)
            st.session_state["imp_label"] = label
        except Exception:  # noqa: BLE001
            st.session_state.pop("imp_result", None)
            notice("error", "The PDF could not be read. Check that it is the NOUN examination timetable and that it is not password protected.")
    r = st.session_state.get("imp_result")
    if r is None:
        return
    from importers.noun_import import build_report, validation_status_for
    rep = build_report(r)
    status = validation_status_for(rep)
    notice({"VALID": "success", "NEEDS_REVIEW": "warning", "INVALID": "error"}[status],
           {"VALID": "All pages and days were extracted and cross-checked.",
            "NEEDS_REVIEW": "Extraction is complete, but some records are flagged for manual review.",
            "INVALID": "The extraction did not cover all expected pages and days. Review the problems below."}[status],
           status.replace("_", " ").title())
    cols = st.columns(4)
    for col, (l, v) in zip(cols, [("Pages processed", f"{rep['pages_processed']} of {rep['pages_total']}"), ("Examination days", str(rep["days_identified"])),
                                  ("Sessions", str(rep["sessions_identified"])), ("Course entries", str(rep["entries_extracted"]))]):
        with col:
            metric_card(l, v)
    cols = st.columns(4)
    for col, (l, v) in zip(cols, [("Unique course codes", str(rep["unique_course_codes"])), ("Batch A / Batch B", f"{rep['batch_a_entries']} / {rep['batch_b_entries']}"),
                                  ("NOUN-prefixed", str(rep["noun_prefixed_entries"])), ("Need review", str(rep["needs_manual_review"]))]):
        with col:
            metric_card(l, v)
    st.caption(f"Independent plain-text count of code-shaped tokens: {rep['independent_token_count']} "
               f"({'matches' if rep['independent_count_matches'] else 'DOES NOT MATCH'} the extracted records). "
               f"Missing codes: {rep['missing_course_codes']}. Missing titles: {rep['missing_course_titles']}.")
    for pg, problem in r.page_problems.items():
        notice("error", problem, f"Page {pg}")
    paginated_table("imp_days", ["Day", "Date", "Page", "Sessions printed", "Records"],
                    [[d.day_no, f"{d.weekday}, {d.date_text}", d.page_no, ", ".join(x.label for x in d.sessions), rep["entries_by_day"].get(str(d.day_no), 0)] for d in r.days],
                    page_size=16)
    flagged = [e for e in r.entries if e.needs_review]
    section_head("Records to review", str(len(flagged)), "sample" if flagged else "ok")
    if flagged:
        paginated_table("imp_review", ["Day", "Page", "Code", "Title", "Reason"],
                        [[e.day_no, e.page_no, e.course_code or "(missing)", e.course_title or "(missing)", "; ".join(e.review_reasons)] for e in flagged], page_size=10)
    with st.expander("Preview extracted records"):
        d_f = st.selectbox("Day", ["All"] + [d.day_no for d in r.days], key="imp_prev_day")
        prev = [e for e in r.entries if d_f == "All" or e.day_no == d_f]
        paginated_table("imp_prev", ["Day", "Session", "Code", "Title", "Batch", "NOUN", "Page"],
                        [[e.day_no, e.session_label, e.course_code, e.course_title, e.batch or "", "Yes" if e.noun_prefixed else "", e.page_no] for e in prev], page_size=12)
    include = st.checkbox("Include records flagged for manual review", True, key="imp_include",
                          help="Flagged records are imported with their review flag so they stay visible and searchable.")
    def do_import():
        try:
            with session_scope() as s:
                out = dsv.import_extraction(s, user, r, include)
            if out.status == "ALREADY_IMPORTED":
                flash("warning", f"This document was already imported. {out.duplicates_prevented} duplicate records were prevented and nothing was changed.")
            else:
                flash("success", f"Imported {out.imported} records. Duplicates prevented: {out.duplicates_prevented}. Skipped for review: {out.skipped_for_review}.")
                st.session_state["ds_open"] = out.dataset_id
        except Exception as exc:  # noqa: BLE001
            flash("error", str(exc) if isinstance(exc, ServiceError) else "The import failed and nothing was saved.")
    confirm_button("Confirm import", "Import the extracted records into the database? Existing data is never changed, and importing the same document again adds nothing.",
                   do_import, "imp_confirm", "primary")


# ----------------------------------------------------------------------------------------------------- exam dataset
def _exam_detail(user, d: Dataset) -> None:
    tabs = st.tabs(["COURSES", "TIMETABLE", "PARALLEL AND CONFLICTS", "VALIDATION", "LECTURE TEST", "EXPORT"])
    with session_scope() as s:
        days = ex.list_days(s, user, d.id)
        times = ex.session_times(s, user, d.id)
    with tabs[0]:
        c1, c2, c3 = st.columns([2, 1, 1])
        text = c1.text_input("Search by course code or title", key="ex_text")
        day = c2.selectbox("Examination day", ["All"] + [x.day_no for x in days], key="ex_day")
        batch = c3.selectbox("Batch", ["All", "A", "B", "No batch"], key="ex_batch")
        c4, c5, c6 = st.columns(3)
        grp = c4.selectbox("Faculty grouping", ["All", "DAYS_1_8", "DAYS_9_16"], key="ex_grp",
                           format_func=lambda v: {"All": "All", "DAYS_1_8": "Days 1 to 8 (Arts, Computing, Education, Management Science, Batch A)",
                                                  "DAYS_9_16": "Days 9 to 16 (Agricultural Science, Law, Science, Health Science, Social Science, Batch B)"}[v])
        noun = c5.selectbox("NOUN prefix", ["All", "NOUN-prefixed", "Not prefixed"], key="ex_noun")
        rev = c6.selectbox("Review", ["All", "Needs review", "No flag"], key="ex_rev")
        with session_scope() as s:
            rows = ex.search_entries(s, user, d.id, text, None if day == "All" else day, {"All": None, "A": "A", "B": "B", "No batch": "NONE"}[batch],
                                     noun_prefixed={"All": None, "NOUN-prefixed": True, "Not prefixed": False}[noun],
                                     needs_review={"All": None, "Needs review": True, "No flag": False}[rev], faculty_group=None if grp == "All" else grp)
        st.caption(f"{len(rows)} course entries match.")
        paginated_table("ex_courses", ["Day", "Date", "Session", "Code", "Title", "Batch", "NOUN", "PDF page", "Review"],
                        [[r.day_no, r.exam_date.strftime("%d %b %Y") if r.exam_date else "", r.session_label, r.course_code, r.course_title, r.batch or "",
                          "Yes" if r.noun_prefixed else "", r.page_no, Badge("Review", "sample") if r.needs_review else ""] for r in rows],
                        page_size=15, empty_title="No matching course entries")
        if rows:
            eid = st.selectbox("Course details", [r.entry_id for r in rows[:500]], key="ex_entry",
                               format_func=lambda i: next(f"{r.course_code} | {r.course_title}" for r in rows if r.entry_id == i))
            r = next(x for x in rows if x.entry_id == eid)
            st.markdown(f'<div class="card"><div class="metric-label">Day {r.day_no}, {r.weekday} {r.exam_date.strftime("%d %B %Y") if r.exam_date else ""}, {r.session_label}</div>'
                        f'<div class="metric-value" style="font-size:1.2rem">{r.course_code} {r.course_title}</div>'
                        f'<div class="metric-note">Base code (reference only): {r.base_code}. Batch: {r.batch or "not a batch course"}. '
                        f'NOUN prefix: {"yes" if r.noun_prefixed else "no"}. Source page: {r.page_no}. Faculty grouping: {r.faculty_group_code or "n/a"}.'
                        f'{"<br>Review: " + "; ".join(r.review_reasons) if r.review_reasons else ""}</div></div>', unsafe_allow_html=True)
    with tabs[1]:
        mode = st.radio("View", ["Courses on a day", "Courses at a time"], horizontal=True, key="ex_mode")
        if mode == "Courses on a day":
            dn = st.selectbox("Day", [x.day_no for x in days], key="ex_view_day", format_func=lambda n: next(f"Day {x.day_no}: {x.weekday}, {x.date_text}" for x in days if x.day_no == n))
            slot = st.selectbox("Session", ["All sessions"] + [1, 2, 3], key="ex_view_slot", format_func=lambda v: v if isinstance(v, str) else f"Session {v}")
            with session_scope() as s:
                rows = ex.search_entries(s, user, d.id, day_no=dn, slot_no=None if slot == "All sessions" else slot)
        else:
            t = st.selectbox("Start time", times, key="ex_view_time", format_func=lambda x: x.strftime("%H:%M"))
            dsel = st.selectbox("Date", ["All dates"] + [x.day_no for x in days], key="ex_view_date",
                                format_func=lambda v: v if isinstance(v, str) else next(f"{x.exam_date:%d %b %Y} (day {x.day_no})" for x in days if x.day_no == v))
            with session_scope() as s:
                rows = ex.search_entries(s, user, d.id, day_no=None if dsel == "All dates" else dsel, session_start=t)
        st.caption(f"{len(rows)} examinations. The original schedule is shown exactly as extracted and cannot be edited here.")
        paginated_table("ex_sched", ["Day", "Date", "Session", "Code", "Title", "Batch"],
                        [[r.day_no, r.exam_date.strftime("%d %b %Y") if r.exam_date else "", r.session_label, r.course_code, r.course_title, r.batch or ""] for r in rows], page_size=20)
    with tabs[2]:
        _parallel(user, d)
    with tabs[3]:
        _validation(user, d)
    with tabs[4]:
        _lecture_test(user, d)
    with tabs[5]:
        c1, c2 = st.columns(2)
        pick = c1.selectbox("PDF scope", ["All days"] + [x.day_no for x in days], key="ex_pdf_day", format_func=lambda v: v if isinstance(v, str) else f"Day {v}")
        try:
            with session_scope() as s:
                pdf = exam_export.export_exam_pdf(s, user, d.id, None if pick == "All days" else pick)
                xls = exam_export.export_exam_excel(s, user, d.id)
            c1.download_button("Download PDF", pdf, file_name=f"exam_timetable_{d.id}.pdf", mime="application/pdf", key="ex_dl_pdf", width="stretch")
            c2.download_button("Download Excel", xls, file_name=f"exam_timetable_{d.id}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="ex_dl_xls", width="stretch")
        except Exception as exc:  # noqa: BLE001
            notice("error", str(exc) if isinstance(exc, ServiceError) else "The export could not be generated.")


def _parallel(user, d: Dataset) -> None:
    notice("info", "Examinations held at the same time are normal: they are for different student populations. They are listed for information and are not conflicts.", "Parallel sessions")
    with session_scope() as s:
        par = ex.parallel_summary(s, user, d.id)
        syn_ds = syn.synthetic_dataset_for(s, d.id)
    paginated_table("ex_par", ["Day", "Date", "Session", "Parallel examinations", "Conflict"],
                    [[p["day_no"], p["date"].strftime("%d %b %Y") if p["date"] else "", p["time"], p["parallel_examinations"], "No"] for p in par], page_size=12)
    section_head("Student-group conflict test")
    if syn_ds is None:
        empty_state("No student groups available", "The PDF contains no student populations. Build the synthetic lecture dataset (LECTURE TEST tab) to obtain synthetic student groups.")
        return
    st.caption("A genuine conflict is one student group registered for two overlapping examinations. The groups tested here are SYNTHETIC.")
    use_dur = st.checkbox("Assume an examination duration", False, key="ex_use_dur", help="The PDF gives start times only. Without a duration, overlap means the same printed session.")
    dur = st.number_input("Assumed duration (minutes)", 15, 600, 120, key="ex_dur", disabled=not use_dur)
    try:
        with session_scope() as s:
            res = ex.detect_group_conflicts(s, user, d.id, syn_ds.id, int(dur) if use_dur else None)
    except ServiceError as exc:
        notice("error", str(exc))
        return
    st.caption(f"Checked {res['groups_checked']} synthetic groups and {res['courses_checked']} course registrations. Method: {res['method']}.")
    if res["conflicts"]:
        notice("warning", f"{len(res['conflicts'])} overlapping examinations found for synthetic student groups. These arise from how the synthetic groups were composed and do not describe real NOUN cohorts.", "Conflicts")
        paginated_table("ex_conf", ["Group", "Day", "Course A", "Time", "Course B", "Time"],
                        [[c["group"], c["day_no"], f"{c['course_a']} {c['title_a']}", c["time_a"], f"{c['course_b']} {c['title_b']}", c["time_b"]] for c in res["conflicts"]], page_size=8)
    else:
        notice("success", "No synthetic student group has two overlapping examinations.", "No conflicts")


def _validation(user, d: Dataset) -> None:
    rep = d.report or {}
    cols = st.columns(4)
    for col, (l, v) in zip(cols, [("Pages processed", f"{rep.get('pages_processed')} of {rep.get('pages_total')}"), ("Days identified", str(rep.get("days_identified"))),
                                  ("Sessions identified", str(rep.get("sessions_identified"))), ("Entries extracted", str(rep.get("entries_extracted")))]):
        with col:
            metric_card(l, v)
    rows = [["Unique course codes", rep.get("unique_course_codes")], ["Batch A entries", rep.get("batch_a_entries")], ["Batch B entries", rep.get("batch_b_entries")],
            ["NOUN-prefixed entries", rep.get("noun_prefixed_entries")], ["Missing course codes", rep.get("missing_course_codes")],
            ["Missing course titles", rep.get("missing_course_titles")], ["Entries needing manual review", rep.get("needs_manual_review")],
            ["Records imported", rep.get("imported")], ["Duplicates prevented", rep.get("duplicates_prevented")], ["Skipped for review", rep.get("skipped_for_review")],
            ["Independent text-token count", rep.get("independent_token_count")], ["Independent count matches", "Yes" if rep.get("independent_count_matches") else "No"],
            ["Validation status", d.validation_status.replace("_", " ").title()]]
    paginated_table("ex_rep", ["Item", "Value"], [[a, "" if b is None else b] for a, b in rows], page_size=20)
    paginated_table("ex_rep_day", ["Day", "Records", "Sessions printed"], [[k, v, ", ".join(rep.get("session_labels_by_day", {}).get(k, []))] for k, v in rep.get("entries_by_day", {}).items()], page_size=16)
    if rep.get("review_reason_counts"):
        paginated_table("ex_rep_rev", ["Review reason", "Records"], [[k, v] for k, v in rep["review_reason_counts"].items()], page_size=10)
    rv = rep.get("revalidation")
    if rv:
        section_head("Latest revalidation", rv["status"].replace("_", " ").title(), STATUS_KIND.get(rv["status"], "muted"))
        paginated_table("ex_rv", ["Check", "Result", "Detail"], [[c["check"], Badge("Passed", "ok") if c["passed"] else Badge("Failed", "error"), c["detail"]] for c in rv["checks"]], page_size=20)


def _lecture_test(user, d: Dataset) -> None:
    with session_scope() as s:
        syn_ds = syn.synthetic_dataset_for(s, d.id)
    notice("warning", "SYNTHETIC TEST DATA. Lecturers, rooms, student groups, populations, availability and teaching requirements below are invented for testing. "
                      "Only course codes and titles come from the PDF. Examination slots are never used as lecture slots.", "Synthetic")
    if syn_ds is None:
        prefixes = st.multiselect("Course code prefixes treated as computing (inferred from the code, not stated in the PDF)", list(syn.DEFAULT_PREFIXES),
                                  default=list(syn.DEFAULT_PREFIXES), key="syn_prefix")
        if st.button("Create synthetic lecture dataset", key="syn_create", type="primary") and \
                attempt(lambda s: syn.build_synthetic_lecture_dataset(s, user, d.id, prefixes), "Synthetic lecture dataset created."):
            st.rerun()
        return
    rep = syn_ds.report or {}
    cols = st.columns(4)
    for col, (l, v) in zip(cols, [("Courses", rep.get("courses")), ("Lecturers", rep.get("lecturers")), ("Rooms", rep.get("rooms")), ("Student groups", rep.get("groups"))]):
        with col:
            metric_card(l, str(v))
    if not has_permission(user, Permission.GENERATE):
        return
    section_head("Generate a lecture timetable")
    c = st.columns(4)
    pop = c[0].number_input("Population size", 4, 500, 40, key="syn_pop")
    gens = c[1].number_input("Maximum generations", 1, 2000, 60, key="syn_gens")
    mut = c[2].number_input("Mutation rate", 0.0, 1.0, 0.02, step=0.005, format="%.3f", key="syn_mut")
    seed = c[3].number_input("Random seed", 0, 10**6, 1, key="syn_seed")
    if st.button("Generate lecture timetable", key="syn_gen", type="primary"):
        try:
            with st.spinner("Running the Genetic Algorithm"):
                with session_scope() as s:
                    ds2 = s.get(Dataset, syn_ds.id)
                    out = syn.generate_lecture_timetable(s, user, ds2, GAConfig(population_size=int(pop), max_generations=int(gens), mutation_rate=float(mut), seed=int(seed)))
            flash("success" if out.is_valid else "warning",
                  f"Lecture timetable generated. Independent validation: {'no hard constraint violations' if out.is_valid else str(len(out.conflicts)) + ' hard violations'}. "
                  f"Initial best fitness {out.result.initial_fitness:.5f}, final {out.result.evaluation.fitness:.5f}.")
            st.session_state["open_timetable"] = out.timetable_id
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            notice("error", str(exc) if isinstance(exc, ServiceError) else "Generation failed. No timetable was saved.")
    with session_scope() as s:
        tt_ids = list(s.scalars(select(DatasetMember.entity_id).where(DatasetMember.dataset_id == syn_ds.id, DatasetMember.entity == "timetable")))
        tts_list = list(s.scalars(select(Timetable).where(Timetable.id.in_(tt_ids or [0])).order_by(Timetable.id)))
    if tts_list:
        paginated_table("syn_tts", ["Timetable", "Version", "Status", "Hard violations", "Soft penalty", "Fitness"],
                        [[t.name, t.version, status_badge(t.status), t.hard_violations, f"{t.soft_penalty:.2f}", f"{t.fitness_score:.6f}"] for t in tts_list], page_size=6)
        b1, b2 = st.columns(2)
        if b1.button("Open latest in TIMETABLE", key="syn_open"):
            st.session_state["open_timetable"] = tts_list[-1].id
            go("TIMETABLE")
            st.rerun()
        if len(tts_list) >= 2:
            a_id = b2.selectbox("Compare latest with", [t.id for t in tts_list[:-1]], key="syn_cmp", format_func=lambda i: next(f"Version {t.version}" for t in tts_list if t.id == i))
            with session_scope() as s:
                res = cmp.compare_timetables(s, user, tts_list[-1].id, a_id)
            notice("info", res.verdict, "Comparison")


def _synthetic_detail(user, d: Dataset) -> None:
    from collections import Counter
    rep = d.report or {}
    notice("warning", rep.get("marker", syn.SYN_NOTE), "Synthetic")
    with session_scope() as s:
        rows = s.execute(select(DatasetMember.entity).where(DatasetMember.dataset_id == d.id)).scalars().all()
    c = Counter(rows)
    paginated_table("syn_members", ["Record type", "Count"], [[k.replace("_", " ").title(), v] for k, v in sorted(c.items())], page_size=12)
    st.caption(d.notes or "")
