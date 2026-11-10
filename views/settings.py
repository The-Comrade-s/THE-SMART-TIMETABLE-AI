from __future__ import annotations

from datetime import time

import streamlit as st

from auth import service as auth_service
from auth.permissions import ROLE_LABELS, Permission, has_permission
from config import get_settings
from database import session_scope
from database.enums import DAYS, ROLES
from services import settings_service as ss
from services import time_slot_service as tss
from ui.components import page_header, section_head
from ui.crud import attempt, confirm_button
from ui.state import flash, form_key, sign_out
from ui.tables import paginated_table, status_badge
from ui.theme import current_theme, set_theme


def render() -> None:
    user = st.session_state["user"]
    page_header("Settings", "Profile, security and application preferences.")
    names = ["PROFILE", "SECURITY", "APPEARANCE", "SESSION"]
    if has_permission(user, Permission.MANAGE_USERS):
        names += ["USERS"]
    if has_permission(user, Permission.MANAGE_SETTINGS):
        names += ["INSTITUTION"]
    if has_permission(user, Permission.IMPORT_DATASETS):
        names += ["DATASETS"]
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["PROFILE"]:
        paginated_table("prof", ["Field", "Value"], [["Full name", user.full_name], ["Email", user.email], ["Role", ROLE_LABELS[user.role]],
                                                      ["Account status", user.status.title()], ["Member since", user.created_at.strftime("%d %B %Y") if user.created_at else ""],
                                                      ["Last sign-in", user.last_login.strftime("%d %B %Y %H:%M") if user.last_login else "First session"]], page_size=10)
    with tabs["SECURITY"]:
        with st.form(form_key("pw")):
            cur = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", help="At least 10 characters with upper case, lower case and a digit.")
            conf = st.text_input("Confirm new password", type="password")
            ok = st.form_submit_button("Change password", type="primary")
        if ok:
            from services.common import ValidationError
            def act(s):
                if new != conf:
                    raise ValidationError("The new passwords do not match.")
                auth_service.change_password(s, user, cur, new)
            if attempt(act, "Password changed.", "pw"):
                st.rerun()
    with tabs["APPEARANCE"]:
        st.session_state["settings_theme"] = current_theme().title()
        choice = st.radio("Theme", ["Dark", "Light"], horizontal=True, key="settings_theme")
        if choice.lower() != current_theme():
            set_theme(choice.lower())
            st.rerun()
    with tabs["SESSION"]:
        with session_scope() as s:
            info = auth_service.session_info(s, st.session_state.get("auth_token", ""))
        rows = [["Signed in", info.created_at.strftime("%d %B %Y %H:%M UTC") if info else ""], ["Session expires", info.expires_at.strftime("%d %B %Y %H:%M UTC") if info else ""],
                ["Environment", get_settings().app_env]]
        paginated_table("sess", ["Item", "Value"], rows, page_size=10)
        if st.button("Sign out", key="settings_signout", type="primary"):
            sign_out()
            st.rerun()
    if "USERS" in tabs:
        with tabs["USERS"]:
            _users(user)
    if "INSTITUTION" in tabs:
        with tabs["INSTITUTION"]:
            _institution(user)
    if "DATASETS" in tabs:
        with tabs["DATASETS"]:
            from views import datasets
            datasets.render()


def _users(user) -> None:
    with session_scope() as s:
        users = auth_service.list_users(s, user)
    paginated_table("usr", ["Name", "Email", "Role", "Status", "Last sign-in"],
                    [[u.full_name, u.email, ROLE_LABELS[u.role], status_badge(u.status), u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else ""] for u in users])
    section_head("Manage a user")
    uid = st.selectbox("User", [u.id for u in users], format_func=lambda i: next(f"{u.full_name} ({u.email})" for u in users if u.id == i), key="usr_sel")
    cur = next(u for u in users if u.id == uid)
    c1, c2 = st.columns(2)
    role = c1.selectbox("Role", ROLES, index=ROLES.index(cur.role), format_func=lambda r: ROLE_LABELS[r], key=f"usr_role_{uid}")
    if c1.button("Update role", key=f"usr_role_btn_{uid}") and attempt(lambda s: auth_service.set_user_role(s, user, uid, role), "Role updated."):
        st.rerun()
    active = cur.status == "ACTIVE"
    def toggle():
        try:
            with session_scope() as s:
                auth_service.set_user_status(s, user, uid, not active)
            flash("success", "Account deactivated." if active else "Account activated.")
        except Exception as exc:  # noqa: BLE001
            flash("error", str(exc))
    with c2:
        confirm_button("Deactivate account" if active else "Activate account", "The user will be signed out immediately." if active else "Activate this account?", toggle, f"usr_tog_{uid}")
    section_head("Create a user")
    with st.form(form_key("usr_new")):
        a, b = st.columns(2)
        name = a.text_input("Full name")
        email = b.text_input("Email address")
        pw = a.text_input("Temporary password", type="password")
        r = b.selectbox("Role", ROLES, index=1, format_func=lambda x: ROLE_LABELS[x])
        ok = st.form_submit_button("Create user", type="primary")
    if ok and attempt(lambda s: auth_service.create_user(s, user, name, email, pw, r), "User created.", "usr_new"):
        st.rerun()


def _institution(user) -> None:
    with session_scope() as s:
        current = ss.get_institution_name(s)
        slots = tss.list_time_slots(s, user)
    with st.form("inst_form"):
        name = st.text_input("Institution name (used in PDF and Excel exports)", current)
        ok = st.form_submit_button("Save institution name", type="primary")
    if ok and attempt(lambda s: ss.set_institution_name(s, user, name), "Institution name saved."):
        st.rerun()
    section_head("Teaching hours")
    st.caption("Active time slots define the permitted teaching hours and the start times the algorithm may use.")
    days_used = sorted({s.day_of_week for s in slots if s.is_active})
    st.write("Active days: " + (", ".join(DAYS[d] for d in days_used) if days_used else "none defined"))
    if slots:
        st.write(f"{sum(1 for s in slots if s.is_active)} active slot(s) of {len(slots)}.")
    with st.form(form_key("slots")):
        days = st.multiselect("Teaching days", range(7), default=[0, 1, 2, 3, 4], format_func=lambda d: DAYS[d])
        a, b, c = st.columns(3)
        start = a.time_input("Day starts", time(8), step=900)
        end = b.time_input("Day ends", time(18), step=900)
        length = c.number_input("Slot length (minutes)", 15, 240, 60, step=15)
        replace = st.checkbox("Replace existing time slots", help="Existing timetables keep their recorded entries.")
        ok = st.form_submit_button("Generate time slots", type="primary")
    if ok and attempt(lambda s: tss.generate_slots(s, user, days, start, end, int(length), replace), "Time slots saved.", "slots"):
        st.rerun()
