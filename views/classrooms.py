from __future__ import annotations

from datetime import time

import streamlit as st

from auth.permissions import Permission, has_permission
from database import session_scope
from database.enums import AVAILABILITY, DAYS, ROOM_TYPES, ROOM_TYPE_LABELS
from services import availability_service as av
from services import classroom_service as svc
from ui.components import empty_state, page_header, section_head
from ui.crud import attempt, confirm_button
from ui.state import flash, form_key
from ui.tables import Badge, paginated_table, status_badge


def availability_editor(kind: str, owner_id: int, can_edit: bool, key: str) -> None:
    user = st.session_state["user"]
    with session_scope() as s:
        rows = av.list_availability(s, user, kind, owner_id)
    paginated_table(f"{key}_tbl", ["Day", "Start", "End", "Status"],
                    [[DAYS[r.day_of_week], r.start_time.strftime("%H:%M"), r.end_time.strftime("%H:%M"), r.status.title()] for r in rows],
                    page_size=14, empty_title="No availability periods",
                    empty_body="Add a period below." if can_edit else "None recorded.")
    if not can_edit:
        return
    with st.form(f"{key}_add_{st.session_state.get(f'_n_{key}', 0)}"):
        days = st.multiselect("Days", range(7), default=[0], format_func=lambda d: DAYS[d])
        c1, c2, c3 = st.columns(3)
        start = c1.time_input("Start time", time(8), step=900)
        end = c2.time_input("End time", time(18), step=900)
        status = c3.selectbox("Status", AVAILABILITY, format_func=str.title)
        ok = st.form_submit_button("Add period", type="primary")
    if ok:
        def act(s):
            if not days:
                from services.common import ValidationError
                raise ValidationError("Select at least one day.")
            for d in days:
                av.add_availability(s, user, kind, owner_id, d, start, end, status)
        from ui.state import reset_form
        if attempt(act, "Availability added.", key):
            st.rerun()
    if rows:
        with st.expander("Edit or remove a period"):
            pid = st.selectbox("Period", [r.id for r in rows], key=f"{key}_pick",
                               format_func=lambda i: next(f"{DAYS[r.day_of_week]} {r.start_time:%H:%M}-{r.end_time:%H:%M} ({r.status.title()})" for r in rows if r.id == i))
            cur = next(r for r in rows if r.id == pid)
            with st.form(f"{key}_edit_{pid}"):
                d = st.selectbox("Day", range(7), index=cur.day_of_week, format_func=lambda x: DAYS[x])
                c1, c2, c3 = st.columns(3)
                s_t = c1.time_input("Start time", cur.start_time, step=900)
                e_t = c2.time_input("End time", cur.end_time, step=900)
                stt = c3.selectbox("Status", AVAILABILITY, index=AVAILABILITY.index(cur.status), format_func=str.title)
                save = st.form_submit_button("Save period")
            if save and attempt(lambda s: av.update_availability(s, user, kind, pid, d, s_t, e_t, stt), "Availability updated."):
                st.rerun()
            def rm():
                with session_scope() as s:
                    av.remove_availability(s, user, kind, pid)
                flash("success", "Availability period removed.")
            confirm_button("Remove period", "Remove this availability period?", rm, f"{key}_rm_{pid}")


def render() -> None:
    user = st.session_state["user"]
    can_edit = has_permission(user, Permission.MANAGE_RECORDS)
    page_header("Classrooms", "Manage rooms and their availability.")
    tabs = st.tabs(["RECORDS", "ADD CLASSROOM"] if can_edit else ["RECORDS"])
    with tabs[0]:
        with session_scope() as s:
            buildings = svc.list_buildings(s, user)
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        search = c1.text_input("Search", key="room_search", placeholder="Room or building")
        building = c2.selectbox("Building", ["All"] + buildings, key="room_b")
        rtype = c3.selectbox("Room type", ["All"] + list(ROOM_TYPES), format_func=lambda v: ROOM_TYPE_LABELS.get(v, v), key="room_t")
        avail = c4.selectbox("Availability", ["All", "Available", "Unavailable"], key="room_a")
        with session_scope() as s:
            rooms = svc.list_classrooms(s, user, search, None if building == "All" else building,
                                        None if rtype == "All" else rtype, None if avail == "All" else avail == "Available")
        paginated_table("room", ["Building", "Room", "Capacity", "Type", "Availability", "Status"],
                        [[r.building, r.name, r.capacity, ROOM_TYPE_LABELS[r.room_type], Badge("Available", "ok") if r.is_available else Badge("Unavailable", "muted"),
                          status_badge(r.status)] for r in rooms], empty_title="No classrooms found")
        if rooms:
            section_head("Room details")
            rid = st.selectbox("Select a classroom", [r.id for r in rooms], key="room_sel",
                               format_func=lambda i: next(f"{r.building} {r.name}" for r in rooms if r.id == i))
            room = next(r for r in rooms if r.id == rid)
            st.write(f"{ROOM_TYPE_LABELS[room.room_type]}, {room.capacity} seats. {room.description or ''}")
            if can_edit:
                with st.expander("Edit room"):
                    with st.form(f"room_edit_{rid}"):
                        name = st.text_input("Room name", room.name)
                        bld = st.text_input("Building", room.building)
                        cap = st.number_input("Capacity", 1, 5000, room.capacity)
                        rt = st.selectbox("Room type", ROOM_TYPES, index=ROOM_TYPES.index(room.room_type), format_func=lambda v: ROOM_TYPE_LABELS[v])
                        desc = st.text_area("Description", room.description or "")
                        isav = st.checkbox("Available for scheduling", room.is_available)
                        save = st.form_submit_button("Save changes", type="primary")
                    if save and attempt(lambda s: svc.update_classroom(s, user, rid, name, bld, cap, rt, desc, isav), "Classroom updated."):
                        st.rerun()
                    active = room.status == "ACTIVE"
                    def toggle():
                        with session_scope() as s:
                            svc.set_classroom_status(s, user, rid, not active)
                        flash("success", "Classroom deactivated." if active else "Classroom activated.")
                    confirm_button("Deactivate classroom" if active else "Activate classroom",
                                   "Inactive rooms are excluded from timetable generation." if active else "Activate this classroom?", toggle, f"room_tog_{rid}")
            st.markdown("**Weekly availability**")
            st.caption("Rooms with no availability periods are treated as available at all permitted teaching times.")
            availability_editor("room", rid, can_edit, f"rav{rid}")
    if can_edit:
        with tabs[1]:
            with st.form(form_key("room_new")):
                name = st.text_input("Room name")
                bld = st.text_input("Building")
                cap = st.number_input("Capacity", 1, 5000, 50)
                rt = st.selectbox("Room type", ROOM_TYPES, format_func=lambda v: ROOM_TYPE_LABELS[v])
                desc = st.text_area("Description")
                ok = st.form_submit_button("Add classroom", type="primary")
            if ok and attempt(lambda s: svc.create_classroom(s, user, name, bld, cap, rt, desc), "Classroom added.", "room_new"):
                st.rerun()
