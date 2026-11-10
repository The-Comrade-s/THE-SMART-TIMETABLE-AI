from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from auth.permissions import Permission, has_permission
from database import session_scope
from database.enums import DAYS, LEVELS, SEMESTERS, TIMETABLE_STATUSES
from exports import excel_export, pdf_export
from services import comparison_service as cmp
from services import department_service as dsvc
from services import generation_service as gsvc
from services import lecturer_service as lsvc
from services import classroom_service as csvc
from services import student_group_service as ssvc
from services import timetable_service as tts
from services.common import ServiceError
from services.timetable_view import load_entry_views
from ui.components import empty_state, metric_card, notice, page_header, section_head
from ui.crud import attempt, confirm_button
from ui.state import flash
from ui.tables import paginated_table, status_badge
from ui.timetable_grid import entry_detail, render_grid
from validation.timetable_validator import CONFLICT_TYPES, TYPE_LABELS


def render() -> None:
    user = st.session_state["user"]
    is_admin = has_permission(user, Permission.VIEW_ALL_TIMETABLES)
    page_header("Timetable", "View, validate, publish and export timetables.")
    with session_scope() as s:
        deps = dsvc.list_departments(s, user) if has_permission(user, Permission.VIEW_RECORDS) else []
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    search = c1.text_input("Search", key="tt_search", placeholder="Timetable name")
    sess_f = c2.text_input("Academic session", key="tt_sess", placeholder="2025/2026")
    sem_f = c3.selectbox("Semester", ["All"] + list(SEMESTERS), format_func=str.title, key="tt_sem")
    stat_f = c4.selectbox("Status", ["All"] + list(TIMETABLE_STATUSES), format_func=str.title, key="tt_stat", disabled=not is_admin)
    d1, _ = st.columns([1, 3])
    dep_labels = {"All departments": None, **{f"{d.code} - {d.name}": d.id for d in deps}}
    dep_f = d1.selectbox("Department", list(dep_labels), key="tt_dep")
    with session_scope() as s:
        tts_list = tts.list_timetables(s, user, search, sess_f.strip() or None, None if sem_f == "All" else sem_f,
                                       dep_labels[dep_f], None if stat_f == "All" else stat_f)
    if not tts_list:
        empty_state("No timetables found", "Generate a timetable, or adjust the filters." if is_admin else "No published timetables match your filters.")
        return
    paginated_table("tt_list", ["Name", "Session", "Semester", "Ver.", "Status", "Hard violations", "Fitness"],
                    [[t.name, t.academic_session, t.semester.title(), t.version, status_badge(t.status),
                      "" if t.hard_violations is None else t.hard_violations, "" if t.fitness_score is None else f"{t.fitness_score:.6f}"] for t in tts_list],
                    page_size=6)
    wanted = st.session_state.pop("open_timetable", None)
    ids = [t.id for t in tts_list]
    idx = ids.index(wanted) if wanted in ids else 0
    tid = st.selectbox("Open timetable", ids, index=idx, key="tt_open", format_func=lambda i: next(f"{t.name} [{t.status.title()}]" for t in tts_list if t.id == i))
    tt = next(t for t in tts_list if t.id == tid)
    _banner(tt)
    names = ["VIEW"] + (["CONFLICTS", "VERSIONS AND ACTIONS", "COMPARE", "REPORT"] if is_admin else []) + ["EXPORT"]
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["VIEW"]:
        _viewer(tid)
    with tabs["EXPORT"]:
        _export(tid, tt)
    if is_admin:
        with tabs["CONFLICTS"]:
            _conflicts(tid)
        with tabs["VERSIONS AND ACTIONS"]:
            _actions(tid, tt)
        with tabs["COMPARE"]:
            _compare(tid, tts_list)
        with tabs["REPORT"]:
            _report(tid, tt)


def _banner(tt) -> None:
    if tt.status == "PUBLISHED":
        notice("success", f"Published timetable, version {tt.version}.", "Published")
    elif tt.is_valid:
        notice("info", f"This timetable is {tt.status.lower()} and has not been published.", "Not published")
    else:
        notice("warning", f"This timetable is {tt.status.lower()} and contains {tt.hard_violations} unresolved hard constraint "
                          "violation(s). It cannot be approved or published.", "Not conflict-free")


def _viewer(tid: int) -> None:
    user = st.session_state["user"]
    can_lists = has_permission(user, Permission.VIEW_RECORDS)
    mode = st.selectbox("View", ["Weekly view", "Department view", "Student group view", "Lecturer view", "Classroom view", "Daily view"], key="tt_mode")
    kw = {}
    with session_scope() as s:
        all_entries = load_entry_views(s, user, tid)
        try:
            conflicts = tts.detect_conflicts(s, user, tid)
        except ServiceError:
            conflicts = []
    bad_ids = {i for c in conflicts for i in c.entry_ids}
    lvl = st.selectbox("Academic level", ["All"] + sorted({e.level for e in all_entries}), key="tt_lvl")
    if lvl != "All":
        all_entries = [e for e in all_entries if e.level == lvl]
    entries = all_entries
    pick = {"Department view": ("Department", lambda e: (e.department_id, e.department), "department"),
            "Student group view": ("Student group", lambda e: (e.group_id, e.group), "group"),
            "Lecturer view": ("Lecturer", lambda e: (e.lecturer_id, e.lecturer), "lecturer"),
            "Classroom view": ("Classroom", lambda e: (e.room_id, e.room), "room")}
    if mode in pick:
        label, fn, attr = pick[mode]
        options = sorted({fn(e) for e in all_entries}, key=lambda x: x[1])
        if not options:
            empty_state("No sessions", "This timetable has no scheduled sessions.")
            return
        chosen = st.selectbox(label, [o[0] for o in options], key=f"tt_pick_{attr}", format_func=lambda i: next(o[1] for o in options if o[0] == i))
        entries = [e for e in all_entries if fn(e)[0] == chosen]
    elif mode == "Daily view":
        used = sorted({e.day for e in all_entries}) or [0]
        day = st.selectbox("Day", used, format_func=lambda d: DAYS[d], key="tt_day")
        entries = [e for e in all_entries if e.day == day]
    c1, c2 = st.columns([4, 1])
    c1.caption(f"{len(entries)} session(s) shown. Overlapping sessions are placed side by side. Sessions in a hard conflict are labelled CONFLICT.")
    with c2:
        components.html('<button onclick="window.parent.print()" style="padding:8px 14px;border-radius:8px;border:1px solid #888;'
                        'font-weight:600;cursor:pointer;background:#fff;color:#111">Print this view</button>', height=48)
    render_grid(entries, bad_ids)
    if entries:
        section_head("Session details")
        eid = st.selectbox("Select a session", [e.entry_id for e in entries], key="tt_entry",
                           format_func=lambda i: next(f"{e.course_code} | {e.day_name} {e.time_label} | {e.group}" for e in entries if e.entry_id == i))
        entry_detail(next(e for e in entries if e.entry_id == eid), eid in bad_ids)


def _conflicts(tid: int) -> None:
    user = st.session_state["user"]
    with session_scope() as s:
        conflicts = tts.detect_conflicts(s, user, tid)
    if not conflicts:
        notice("success", "Independent validation found no hard constraint violations.", "Conflict-free")
        return
    notice("error", f"Independent validation found {len(conflicts)} hard constraint violation(s).", "Conflicts")
    c1, c2 = st.columns(2)
    types = c1.multiselect("Conflict type", CONFLICT_TYPES, format_func=lambda t: TYPE_LABELS[t], key="cf_type")
    sev = c2.multiselect("Severity", ["CRITICAL", "HIGH", "MEDIUM"], key="cf_sev")
    rows = [c.as_row() for c in conflicts if (not types or c.type in types) and (not sev or c.severity in sev)]
    paginated_table("cf", ["Type", "Severity", "Course", "Lecturer", "Classroom", "Group", "Day", "Start", "End", "Explanation"],
                    [[r["type_label"], r["severity"], r["course"], r["lecturer"], r["classroom"], r["group"], r["day"], r["start"], r["end"], r["explanation"]] for r in rows],
                    page_size=8, empty_title="No conflicts match the filters")


def _actions(tid: int, tt) -> None:
    user = st.session_state["user"]
    with session_scope() as s:
        versions = tts.versions_of(s, user, tid)
    section_head("Version history")
    paginated_table("ver", ["Version", "Name", "Status", "Hard violations", "Soft penalty"],
                    [[v.version, v.name, status_badge(v.status), "" if v.hard_violations is None else v.hard_violations,
                      "" if v.soft_penalty is None else f"{v.soft_penalty:.2f}"] for v in versions], page_size=6)
    section_head("Lifecycle")
    st.caption("Lifecycle: Generated, Validated, Approved, Published, Archived. Only valid timetables can be approved; only approved timetables can be published.")
    c1, c2, c3, c4 = st.columns(4)

    def run(fn, msg):
        def inner():
            try:
                with session_scope() as s:
                    fn(s)
                flash("success", msg)
            except Exception as exc:  # noqa: BLE001
                flash("error", str(exc) if isinstance(exc, (ServiceError,)) or exc.__class__.__name__ == "PermissionDenied" else "The action could not be completed.")
        return inner
    with c1:
        confirm_button("Run validation", "Run the independent validator now?", run(lambda s: tts.revalidate(s, user, tid), "Validation completed."), f"act_val_{tid}")
    with c2:
        confirm_button("Approve", "Approve this timetable? It is re-validated first and rejected if any hard violation exists.",
                       run(lambda s: tts.approve(s, user, tid), "Timetable approved."), f"act_app_{tid}")
    with c3:
        replace = st.checkbox("Replace the currently published version", key=f"rep_{tid}", help="The previous published version is archived, never deleted.")
        confirm_button("Publish", "Publish this approved timetable?", run(lambda s: tts.publish(s, user, tid, replace), "Timetable published."), f"act_pub_{tid}")
    with c4:
        confirm_button("Archive", "Archive this timetable? It stays available as history.", run(lambda s: tts.archive(s, user, tid), "Timetable archived."), f"act_arc_{tid}")
    if has_permission(user, Permission.GENERATE):
        confirm_button("Create revision (new version)", "Copy this timetable into a new version. The original is preserved.",
                       run(lambda s: tts.create_revision(s, user, tid), "New version created."), f"act_rev_{tid}")
        if st.button("Re-optimise with different parameters", key=f"reopt_{tid}"):
            st.session_state["reopt_parent"] = tid
            from ui.navigation import go
            go("GENERATE TIMETABLE")
            st.rerun()
    if has_permission(user, Permission.VIEW_HISTORY):
        section_head("Audit trail")
        with session_scope() as s:
            trail = tts.audit_trail(s, user, tid)
        paginated_table("aud", ["When", "Action", "Details"], [[a.created_at.strftime("%Y-%m-%d %H:%M"), a.action.replace("_", " ").title(), a.details or ""] for a in trail], page_size=6)


def _compare(tid: int, tts_list) -> None:
    user = st.session_state["user"]
    others = [t for t in tts_list if t.id != tid]
    if not others:
        empty_state("Nothing to compare", "At least two timetables are needed.")
        return
    other = st.selectbox("Compare with", [t.id for t in others], key="cmp_other", format_func=lambda i: next(f"{t.name} [{t.status.title()}]" for t in others if t.id == i))
    with session_scope() as s:
        c = cmp.compare_timetables(s, user, tid, other)
    notice("info", c.verdict, "Result")
    st.caption("A is the timetable opened above; B is the one selected here.")
    paginated_table("cmp_m", ["Metric", "A", "B"], [[m["metric"], m["A"], m["B"]] for m in c.metrics], page_size=10)
    section_head("Session differences")
    if c.identical:
        st.write("Both timetables place every session identically.")
    else:
        paginated_table("cmp_c", ["Course", "Group", "Session", "Change", "In A", "In B"], [[x["course"], x["group"], x["session"], x["change"], x["A"], x["B"]] for x in c.changes], page_size=8)


def _report(tid: int, tt) -> None:
    user = st.session_state["user"]
    from sqlalchemy import select
    from database.models import GenerationHistory
    with session_scope() as s:
        h = s.scalar(select(GenerationHistory).where(GenerationHistory.timetable_id == tid).order_by(GenerationHistory.id.desc()))
    if h is None:
        empty_state("No generation record", "This timetable was not produced by a generation run (for example, a copied revision).")
        return
    imp = ((h.final_fitness - h.initial_fitness) / h.initial_fitness * 100) if h.initial_fitness else 0
    cols = st.columns(4)
    for col, (l, v) in zip(cols, [("Initial fitness", f"{h.initial_fitness:.5f}"), ("Final fitness", f"{h.final_fitness:.5f}"),
                                   ("Improvement", f"{imp:.1f}%"), ("Generations", str(h.generations))]):
        with col:
            metric_card(l, v)
    st.write(f"Best generation {h.best_generation}. Execution time {h.execution_seconds:.2f} s. Termination: {h.termination_reason}.")
    br = h.constraint_breakdown or {}
    a, b = st.columns(2)
    with a:
        st.markdown("**Hard constraints (algorithm evaluation)**")
        paginated_table("rep_h", ["Constraint", "Count"], [[k, v] for k, v in (br.get("hard") or {}).items()], page_size=12)
    with b:
        st.markdown("**Soft constraint penalties**")
        paginated_table("rep_s", ["Constraint", "Penalty"], [[k, v] for k, v in (br.get("soft") or {}).items()], page_size=12)
    with session_scope() as s:
        data = pdf_export.export_generation_report_pdf(s, user, tid)
    st.download_button("Download generation report (PDF)", data, file_name=f"generation_report_{tid}.pdf", mime="application/pdf", key=f"dl_rep_{tid}")


def _export(tid: int, tt) -> None:
    user = st.session_state["user"]
    if tt.status != "PUBLISHED":
        notice("warning", "This timetable is not published. Exports are marked with its status and are not official.", "Draft export")
    kind = st.selectbox("Export", ["Complete university timetable", "Department timetable", "Student group timetable", "Lecturer timetable", "Classroom timetable"], key="ex_kind")
    code = {"Complete university timetable": "university", "Department timetable": "department", "Student group timetable": "group",
            "Lecturer timetable": "lecturer", "Classroom timetable": "classroom"}[kind]
    owner = None
    if code != "university":
        with session_scope() as s:
            ents = load_entry_views(s, user, tid)
        fn = {"department": lambda e: (e.department_id, e.department), "group": lambda e: (e.group_id, e.group),
              "lecturer": lambda e: (e.lecturer_id, e.lecturer), "classroom": lambda e: (e.room_id, e.room)}[code]
        opts = sorted({fn(e) for e in ents}, key=lambda x: x[1])
        if not opts:
            empty_state("Nothing to export", "This timetable has no sessions.")
            return
        owner = st.selectbox("Select", [o[0] for o in opts], key=f"ex_owner_{code}", format_func=lambda i: next(o[1] for o in opts if o[0] == i))
    c1, c2 = st.columns(2)
    try:
        with session_scope() as s:
            pdf = pdf_export.export_timetable_pdf(s, user, tid, code, owner)
            xls = excel_export.export_timetable_excel(s, user, tid, code, owner)
    except Exception as exc:  # noqa: BLE001
        notice("error", str(exc) if isinstance(exc, ServiceError) else "The export could not be generated. Please try again.")
        return
    c1.download_button("Download PDF", pdf, file_name=f"timetable_{tid}_{code}.pdf", mime="application/pdf", key=f"dl_pdf_{tid}_{code}", width="stretch")
    c2.download_button("Download Excel", xls, file_name=f"timetable_{tid}_{code}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_xls_{tid}_{code}", width="stretch")
