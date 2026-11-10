from __future__ import annotations

import streamlit as st

from auth.permissions import Permission, has_permission
from database import session_scope
from database.enums import DAYS, LEVELS, ROOM_TYPES, ROOM_TYPE_LABELS, SEMESTERS
from services import assignment_service as asvc
from services import course_service as svc
from services import department_service as dsvc
from services import lecturer_service as lsvc
from services import student_group_service as gsvc
from services.course_service import default_session_pattern
from ui.components import notice, page_header, section_head
from ui.crud import attempt, confirm_button, options
from ui.state import flash, form_key
from ui.tables import paginated_table, status_badge


def _session_default() -> str:
    from datetime import date
    y = date.today().year if date.today().month >= 8 else date.today().year - 1
    return f"{y}/{y + 1}"


def render() -> None:
    page_header("Courses", "Courses, student groups and course assignments.")
    t1, t2, t3 = st.tabs(["COURSES", "STUDENT GROUPS", "ASSIGNMENTS"])
    with t1:
        _courses()
    with t2:
        _groups()
    with t3:
        _assignments()


def _pattern_input(weekly: int, key: str, current=None):
    default = ", ".join(str(m) for m in (current or default_session_pattern(weekly)))
    raw = st.text_input("Weekly session durations in minutes, comma separated", default, key=key,
                        help="For example 120, 60 means two sessions per week: one of two hours and one of one hour. "
                             "The durations must add up to the weekly lecture duration.")
    try:
        return [int(x) for x in raw.replace(" ", "").split(",") if x]
    except ValueError:
        return []


def _courses() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_RECORDS)
    with session_scope() as s:
        deps = dsvc.list_departments(s, user)
    dep_labels, dep_map = options(deps, lambda d: f"{d.code} - {d.name}")
    sub = st.tabs(["RECORDS", "ADD COURSE"] if can_edit else ["RECORDS"])
    with sub[0]:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        search = c1.text_input("Search", key="crs_search", placeholder="Code or title")
        dep_f = c2.selectbox("Department", ["All"] + dep_labels, key="crs_dep")
        lvl_f = c3.selectbox("Level", ["All"] + list(LEVELS), key="crs_lvl")
        sem_f = c4.selectbox("Semester", ["All"] + list(SEMESTERS), format_func=str.title, key="crs_sem")
        with session_scope() as s:
            courses = svc.list_courses(s, user, search, dep_map.get(dep_f), None if lvl_f == "All" else lvl_f, None if sem_f == "All" else sem_f)
        dcode = {d.id: d.code for d in deps}
        paginated_table("crs", ["Code", "Title", "Dept", "Level", "Semester", "Units", "Weekly (min)", "Room type", "Status"],
                        [[c.code, c.title, dcode.get(c.department_id, ""), c.level, c.semester.title(), c.credit_units, c.weekly_minutes,
                          ROOM_TYPE_LABELS[c.required_room_type], status_badge(c.status)] for c in courses], empty_title="No courses found")
        if courses:
            section_head("Course details")
            cid = st.selectbox("Select a course", [c.id for c in courses], key="crs_sel", format_func=lambda i: next(f"{c.code} - {c.title}" for c in courses if c.id == i))
            with session_scope() as s:
                det = svc.course_detail(s, user, cid)
                c = det["course"]
                st.write(f"**{c.code}: {c.title}**. Weekly sessions (minutes): {', '.join(map(str, det['sessions']))}. "
                         f"{len(det['assignments'])} assignment(s).")
            if can_edit:
                with st.expander("Edit course or change status"):
                    with st.form(f"crs_edit_{cid}"):
                        a, b = st.columns(2)
                        code = a.text_input("Course code", c.code)
                        title = b.text_input("Course title", c.title)
                        units = a.number_input("Credit units", 1, 12, c.credit_units)
                        weekly = b.number_input("Weekly lecture duration (minutes)", 30, 2400, c.weekly_minutes, step=30)
                        cur_dep = next((l for l, i in dep_map.items() if i == c.department_id), dep_labels[0])
                        dep = a.selectbox("Department", dep_labels, index=dep_labels.index(cur_dep))
                        lvl = b.selectbox("Academic level", LEVELS, index=LEVELS.index(c.level))
                        sem = a.selectbox("Semester", SEMESTERS, index=SEMESTERS.index(c.semester), format_func=str.title)
                        rt = b.selectbox("Required room type", ROOM_TYPES, index=ROOM_TYPES.index(c.required_room_type), format_func=lambda v: ROOM_TYPE_LABELS[v])
                        pattern = _pattern_input(int(weekly), f"crs_pat_{cid}", det["sessions"])
                        save = st.form_submit_button("Save changes", type="primary")
                    if save and attempt(lambda s: svc.update_course(s, user, cid, code, title, units, dep_map[dep], lvl, sem, weekly, rt, pattern), "Course updated."):
                        st.rerun()
                    active = c.status == "ACTIVE"
                    def toggle():
                        with session_scope() as s:
                            svc.set_course_status(s, user, cid, not active)
                        flash("success", "Course deactivated." if active else "Course activated.")
                    confirm_button("Deactivate course" if active else "Activate course", "Inactive courses are excluded from generation." if active else "Activate this course?", toggle, f"crs_tog_{cid}")
    if can_edit:
        with sub[1]:
            if not dep_labels:
                st.info("Add a department first.")
                return
            with st.form(form_key("crs_new")):
                a, b = st.columns(2)
                code = a.text_input("Course code")
                title = b.text_input("Course title")
                units = a.number_input("Credit units", 1, 12, 3)
                weekly = b.number_input("Weekly lecture duration (minutes)", 30, 2400, 180, step=30)
                dep = a.selectbox("Department", [l for l, i in dep_map.items() if i])
                lvl = b.selectbox("Academic level", LEVELS)
                sem = a.selectbox("Semester", SEMESTERS, format_func=str.title)
                rt = b.selectbox("Required room type", ROOM_TYPES, format_func=lambda v: ROOM_TYPE_LABELS[v])
                pattern = _pattern_input(int(weekly), "crs_new_pat")
                ok = st.form_submit_button("Add course", type="primary")
            if ok and attempt(lambda s: svc.create_course(s, user, code, title, units, dep_map[dep], lvl, sem, weekly, rt, pattern), "Course added.", "crs_new"):
                st.rerun()


def _groups() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_RECORDS)
    with session_scope() as s:
        deps = dsvc.list_departments(s, user)
    dep_labels, dep_map = options(deps, lambda d: f"{d.code} - {d.name}")
    sub = st.tabs(["RECORDS", "ADD GROUP"] if can_edit else ["RECORDS"])
    with sub[0]:
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("Search", key="grp_search", placeholder="Group or programme")
        dep_f = c2.selectbox("Department", ["All"] + dep_labels, key="grp_dep")
        lvl_f = c3.selectbox("Level", ["All"] + list(LEVELS), key="grp_lvl")
        with session_scope() as s:
            groups = gsvc.list_groups(s, user, search, dep_map.get(dep_f), None if lvl_f == "All" else lvl_f)
        dcode = {d.id: d.code for d in deps}
        paginated_table("grp", ["Group", "Dept", "Level", "Programme", "Students", "Session", "Status"],
                        [[g.name, dcode.get(g.department_id, ""), g.level, g.programme, g.population, g.academic_session, status_badge(g.status)] for g in groups],
                        empty_title="No student groups found")
        if groups:
            gid = st.selectbox("Select a group", [g.id for g in groups], key="grp_sel", format_func=lambda i: next(g.name for g in groups if g.id == i))
            g = next(x for x in groups if x.id == gid)
            with session_scope() as s:
                assigns = gsvc.group_courses(s, user, gid)
                st.write(f"**Associated courses ({len(assigns)}):** " + (", ".join(sorted({a.course.code for a in assigns})) or "none yet"))
            if can_edit:
                with st.expander("Edit group or change status"):
                    with st.form(f"grp_edit_{gid}"):
                        a, b = st.columns(2)
                        name = a.text_input("Group name", g.name)
                        prog = b.text_input("Programme", g.programme)
                        cur_dep = next((l for l, i in dep_map.items() if i == g.department_id), dep_labels[0])
                        dep = a.selectbox("Department", dep_labels, index=dep_labels.index(cur_dep))
                        lvl = b.selectbox("Academic level", LEVELS, index=LEVELS.index(g.level))
                        pop = a.number_input("Student population", 1, 20000, g.population)
                        sess = b.text_input("Academic session", g.academic_session)
                        save = st.form_submit_button("Save changes", type="primary")
                    if save and attempt(lambda s: gsvc.update_group(s, user, gid, name, dep_map[dep], lvl, prog, pop, sess), "Student group updated."):
                        st.rerun()
                    active = g.status == "ACTIVE"
                    def toggle():
                        with session_scope() as s:
                            gsvc.set_group_status(s, user, gid, not active)
                        flash("success", "Group deactivated." if active else "Group activated.")
                    confirm_button("Deactivate group" if active else "Activate group", "Inactive groups are excluded from generation." if active else "Activate this group?", toggle, f"grp_tog_{gid}")
    if can_edit:
        with sub[1]:
            if not dep_labels:
                st.info("Add a department first.")
                return
            with st.form(form_key("grp_new")):
                a, b = st.columns(2)
                name = a.text_input("Group name")
                prog = b.text_input("Programme")
                dep = a.selectbox("Department", [l for l, i in dep_map.items() if i])
                lvl = b.selectbox("Academic level", LEVELS)
                pop = a.number_input("Student population", 1, 20000, 50)
                sess = b.text_input("Academic session", _session_default())
                ok = st.form_submit_button("Create group", type="primary")
            if ok and attempt(lambda s: gsvc.create_group(s, user, name, dep_map[dep], lvl, prog, pop, sess), "Student group created.", "grp_new"):
                st.rerun()


def _assignments() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_RECORDS)
    with session_scope() as s:
        courses = [c for c in svc.list_courses(s, user, status="ACTIVE")]
        lecs = [l for l in lsvc.list_lecturers(s, user, status="ACTIVE")]
        groups = [g for g in gsvc.list_groups(s, user, status="ACTIVE")]
        all_assign = asvc.list_assignments(s, user)
        rows = [[a.course.code, a.lecturer.full_name, a.group.name, a.academic_session, a.semester.title(), status_badge(a.status)] for a in all_assign]
    sub = st.tabs(["RECORDS", "NEW ASSIGNMENT"] if can_edit else ["RECORDS"])
    with sub[0]:
        paginated_table("asg", ["Course", "Lecturer", "Group", "Session", "Semester", "Status"], rows, empty_title="No assignments yet")
        if all_assign and can_edit:
            aid = st.selectbox("Select an assignment", [a.id for a in all_assign], key="asg_sel",
                               format_func=lambda i: next(f"{a.course.code} | {a.lecturer.full_name} | {a.group.name} | {a.academic_session} {a.semester.title()}" for a in all_assign if a.id == i))
            cur = next(a for a in all_assign if a.id == aid)
            active = cur.status == "ACTIVE"
            def toggle():
                with session_scope() as s:
                    asvc.set_assignment_status(s, user, aid, not active)
                flash("success", "Assignment deactivated." if active else "Assignment activated.")
            def remove():
                try:
                    with session_scope() as s:
                        asvc.delete_assignment(s, user, aid)
                    flash("success", "Assignment deleted.")
                except Exception as exc:  # noqa: BLE001
                    flash("error", str(exc))
            c1, c2 = st.columns(2)
            with c1:
                confirm_button("Deactivate assignment" if active else "Activate assignment", "Inactive assignments are excluded from generation." if active else "Activate this assignment?", toggle, f"asg_tog_{aid}")
            with c2:
                confirm_button("Delete assignment", "Delete this assignment? This is not possible if it appears in generated timetables.", remove, f"asg_del_{aid}")
    if can_edit:
        with sub[1]:
            if not (courses and lecs and groups):
                notice("info", "Create at least one active course, lecturer and student group first.")
                return
            c_lab = {f"{c.code} - {c.title}": c for c in courses}
            l_lab = {f"{l.full_name} ({l.staff_id})": l.id for l in lecs}
            g_lab = {f"{g.name} (level {g.level}, {g.academic_session})": g for g in groups}
            with st.form(form_key("asg_new")):
                course = st.selectbox("Course", list(c_lab))
                lec = st.selectbox("Lecturer", list(l_lab))
                grp = st.selectbox("Student group", list(g_lab))
                a, b = st.columns(2)
                sess = a.text_input("Academic session", g_lab[grp].academic_session if grp in g_lab else _session_default())
                sem = b.selectbox("Semester", SEMESTERS, index=SEMESTERS.index(c_lab[course].semester), format_func=str.title)
                ok = st.form_submit_button("Save assignment", type="primary")
            if ok and attempt(lambda s: asvc.create_assignment(s, user, c_lab[course].id, l_lab[lec], g_lab[grp].id, sess, sem), "Assignment saved.", "asg_new"):
                st.rerun()
