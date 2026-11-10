from __future__ import annotations

import streamlit as st

from auth.permissions import Permission, has_permission
from database import session_scope
from services import department_service as svc
from ui.components import empty_state, page_header, section_head
from ui.crud import attempt, confirm_button
from ui.state import flash, form_key
from ui.tables import paginated_table, status_badge


def render() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_DEPARTMENTS)
    page_header("Departments", "Manage academic departments.")
    tabs = st.tabs(["RECORDS", "ADD DEPARTMENT"] if can_edit else ["RECORDS"])
    with tabs[0]:
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("Search", key="dep_search", placeholder="Name or code")
        with session_scope() as s:
            faculties = svc.list_faculties(s, user)
        status = c2.selectbox("Status", ["All", "ACTIVE", "INACTIVE"], key="dep_status")
        faculty = c3.selectbox("Faculty", ["All"] + faculties, key="dep_fac")
        with session_scope() as s:
            deps = svc.list_departments(s, user, search, None if status == "All" else status, None if faculty == "All" else faculty)
        paginated_table("dep", ["Code", "Name", "Faculty", "Status"], [[d.code, d.name, d.faculty or "", status_badge(d.status)] for d in deps],
                        empty_title="No departments found")
        if deps:
            section_head("Department details")
            chosen = st.selectbox("Select a department", [d.id for d in deps], format_func=lambda i: next(f"{d.code} - {d.name}" for d in deps if d.id == i), key="dep_sel")
            with session_scope() as s:
                det = svc.department_detail(s, user, chosen)
                dep = det["department"]
                st.write(f"**{dep.name}** ({dep.code}). Faculty: {dep.faculty or 'not set'}. {dep.description or ''}")
                a, b = st.columns(2)
                a.markdown(f"**Lecturers ({len(det['lecturers'])})**")
                for l in det["lecturers"][:15]:
                    a.write(f"{l.full_name} ({l.staff_id})")
                b.markdown(f"**Courses ({len(det['courses'])})**")
                for c in det["courses"][:15]:
                    b.write(f"{c.code} - {c.title}")
            if can_edit:
                _edit(chosen, dep)
    if can_edit:
        with tabs[1]:
            with st.form(form_key("dep_new")):
                name = st.text_input("Department name")
                code = st.text_input("Department code", help="Must be unique, for example CSC")
                faculty = st.text_input("Faculty")
                desc = st.text_area("Description")
                ok = st.form_submit_button("Add department", type="primary")
            if ok and attempt(lambda s: svc.create_department(s, user, name, code, faculty, desc), "Department added.", "dep_new"):
                st.rerun()


def _edit(dep_id: int, dep) -> None:
    user = st.session_state["user"]
    with st.expander("Edit or change status"):
        with st.form(f"dep_edit_{dep_id}"):
            name = st.text_input("Department name", dep.name)
            code = st.text_input("Department code", dep.code)
            faculty = st.text_input("Faculty", dep.faculty or "")
            desc = st.text_area("Description", dep.description or "")
            saved = st.form_submit_button("Save changes", type="primary")
        if saved and attempt(lambda s: svc.update_department(s, user, dep_id, name, code, faculty, desc), "Department updated."):
            st.rerun()
        active = dep.status == "ACTIVE"
        def toggle():
            with session_scope() as s:
                svc.set_department_status(s, user, dep_id, not active)
            flash("success", "Department deactivated." if active else "Department activated.")
        confirm_button("Deactivate department" if active else "Activate department",
                       "Deactivated departments cannot be selected for new records." if active else "Activate this department?", toggle, f"dep_tog_{dep_id}")
