from __future__ import annotations

import streamlit as st

from auth.permissions import Permission, has_permission
from database import session_scope
from services import dashboard_service as ds
from services import timetable_service as tts
from ui.charts import bar_chart, histogram, runs_chart, violations_chart
from ui.components import empty_state, metric_card, page_header, section_head
from ui.state import current_user
from ui.tables import paginated_table, status_badge


def render() -> None:
    user = st.session_state["user"]
    page_header("Dashboard", "Live overview of institutional records and timetable generation.")
    if not has_permission(user, Permission.VIEW_RECORDS):
        _viewer(user)
        return
    with session_scope() as s:
        m = ds.metrics(s, user)
        cpd, lpd, caps = ds.courses_per_department(s, user), ds.lecturers_per_department(s, user), ds.classroom_capacities(s, user)
        runs = ds.generation_runs(s, user) if has_permission(user, Permission.VIEW_HISTORY) else []
    section_head("Institutional records")
    cards = [("Departments", m["departments"]), ("Lecturers", m["lecturers"]), ("Courses", m["courses"]),
             ("Classrooms", m["classrooms"]), ("Student groups", m["student_groups"]), ("Generated timetables", m["timetables"]),
             ("Published timetables", m["published"]), ("Draft timetables", m["draft"])]
    for row in (cards[:4], cards[4:]):
        for col, (label, val) in zip(st.columns(4), row):
            with col:
                metric_card(label, str(val))
        st.write("")
    section_head("Records overview")
    a, b = st.columns(2)
    with a:
        st.markdown("**Courses per department**")
        if cpd:
            st.plotly_chart(bar_chart([c for c, _ in cpd], [n for _, n in cpd], "Department", "Courses"), width="stretch", config={"displayModeBar": False})
        else:
            empty_state("No courses yet", "Register courses to see their distribution.")
    with b:
        st.markdown("**Lecturers per department**")
        if lpd:
            st.plotly_chart(bar_chart([c for c, _ in lpd], [n for _, n in lpd], "Department", "Lecturers"), width="stretch", config={"displayModeBar": False})
        else:
            empty_state("No lecturers yet", "Register lecturers to see their distribution.")
    st.markdown("**Classroom capacity distribution**")
    if caps:
        st.plotly_chart(histogram(caps, "Seats"), width="stretch", config={"displayModeBar": False})
    else:
        empty_state("No classrooms yet", "Register classrooms to see capacity distribution.")
    if has_permission(user, Permission.VIEW_HISTORY):
        section_head("Timetable generation")
        if runs:
            labels = [str(i + 1) for i in range(len(runs))]
            c, d = st.columns(2)
            with c:
                st.markdown("**Generation history: hard violations per run**")
                st.plotly_chart(violations_chart(labels, [r.hard_violations or 0 for r in runs]), width="stretch", config={"displayModeBar": False})
            with d:
                st.markdown("**Optimisation performance: initial and final fitness**")
                st.plotly_chart(runs_chart(labels, [r.initial_fitness for r in runs], [r.final_fitness for r in runs]), width="stretch", config={"displayModeBar": False})
        else:
            empty_state("No generation runs yet", "Run a generation to see history and optimisation performance.")


def _viewer(user) -> None:
    with session_scope() as s:
        tts_list = tts.list_timetables(s, user)
    section_head("Published timetables")
    if not tts_list:
        empty_state("No published timetables", "Published timetables will appear here once an administrator publishes one.")
        return
    paginated_table("dash_pub", ["Name", "Session", "Semester", "Version", "Status"],
                    [[t.name, t.academic_session, t.semester.title(), t.version, status_badge(t.status)] for t in tts_list])
