from __future__ import annotations

import streamlit as st

from auth.permissions import Permission, has_permission
from database import session_scope
from database.enums import EMPLOYMENT
from services import department_service as dsvc
from services import lecturer_service as svc
from ui.components import page_header, section_head
from ui.crud import attempt, confirm_button, options
from ui.state import flash, form_key
from ui.tables import paginated_table, status_badge
from views.classrooms import availability_editor


def render() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_RECORDS)
    page_header("Lecturers", "Register lecturers and manage their weekly availability.")
    with session_scope() as s:
        deps = [d for d in dsvc.list_departments(s, user)]
    dep_labels, dep_map = options(deps, lambda d: f"{d.code} - {d.name}")
    tabs = st.tabs(["RECORDS", "REGISTER LECTURER"] if can_edit else ["RECORDS"])
    with tabs[0]:
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("Search", key="lec_search", placeholder="Name, staff ID or email")
        dep_f = c2.selectbox("Department", ["All"] + dep_labels, key="lec_dep")
        status = c3.selectbox("Status", ["All", "ACTIVE", "INACTIVE"], key="lec_status")
        with session_scope() as s:
            lecs = svc.list_lecturers(s, user, search, dep_map.get(dep_f), None if status == "All" else status)
        dep_name = {d.id: d.code for d in deps}
        paginated_table("lec", ["Staff ID", "Name", "Department", "Email", "Employment", "Status"],
                        [[l.staff_id, l.full_name, dep_name.get(l.department_id, ""), l.email, l.employment_status.replace("_", " ").title(),
                          status_badge(l.status)] for l in lecs], empty_title="No lecturers found")
        if lecs:
            section_head("Lecturer profile")
            lid = st.selectbox("Select a lecturer", [l.id for l in lecs], key="lec_sel",
                               format_func=lambda i: next(f"{l.full_name} ({l.staff_id})" for l in lecs if l.id == i))
            with session_scope() as s:
                prof = svc.lecturer_profile(s, user, lid)
                lec = prof["lecturer"]
                st.write(f"**{lec.full_name}**, {prof['department'].name}. {lec.email}. Phone: {lec.phone or 'not set'}.")
                if prof["assignments"]:
                    st.markdown("**Course assignments**")
                    paginated_table("lec_assign", ["Course", "Group", "Session", "Semester"],
                                    [[a.course.code, a.group.name, a.academic_session, a.semester.title()] for a in prof["assignments"]], page_size=6)
            if can_edit:
                with st.expander("Edit lecturer or change status"):
                    with st.form(f"lec_edit_{lid}"):
                        a, b = st.columns(2)
                        sid = a.text_input("Staff ID", lec.staff_id)
                        email = b.text_input("Email", lec.email)
                        fn = a.text_input("First name", lec.first_name)
                        ln = b.text_input("Last name", lec.last_name)
                        phone = a.text_input("Phone", lec.phone or "")
                        emp = b.selectbox("Employment status", EMPLOYMENT, index=EMPLOYMENT.index(lec.employment_status), format_func=lambda v: v.replace("_", " ").title())
                        cur_dep = next((l for l, i in dep_map.items() if i == lec.department_id), dep_labels[0])
                        dep = st.selectbox("Department", dep_labels, index=dep_labels.index(cur_dep))
                        save = st.form_submit_button("Save changes", type="primary")
                    if save and attempt(lambda s: svc.update_lecturer(s, user, lid, sid, fn, ln, email, phone, dep_map[dep], emp), "Lecturer updated."):
                        st.rerun()
                    active = lec.status == "ACTIVE"
                    def toggle():
                        with session_scope() as s:
                            svc.set_lecturer_status(s, user, lid, not active)
                        flash("success", "Lecturer deactivated." if active else "Lecturer activated.")
                    confirm_button("Deactivate lecturer" if active else "Activate lecturer",
                                   "Inactive lecturers are excluded from timetable generation." if active else "Activate this lecturer?", toggle, f"lec_tog_{lid}")
            st.markdown("**Weekly availability**")
            st.caption("A lecturer needs at least one available period before timetables can be generated. Preferred periods are favoured by the optimiser.")
            availability_editor("lecturer", lid, can_edit, f"lav{lid}")
    if can_edit:
        with tabs[1]:
            if not dep_labels:
                st.info("Add a department first.")
                return
            with st.form(form_key("lec_new")):
                a, b = st.columns(2)
                sid = a.text_input("Staff ID")
                email = b.text_input("Email")
                fn = a.text_input("First name")
                ln = b.text_input("Last name")
                phone = a.text_input("Phone")
                emp = b.selectbox("Employment status", EMPLOYMENT, format_func=lambda v: v.replace("_", " ").title())
                dep = st.selectbox("Department", [l for l, i in dep_map.items() if i is not None])
                ok = st.form_submit_button("Register lecturer", type="primary")
            if ok and attempt(lambda s: svc.create_lecturer(s, user, sid, fn, ln, email, phone, dep_map[dep], emp), "Lecturer registered.", "lec_new"):
                st.rerun()
