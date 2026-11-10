"""Sidebar navigation. Labels are uppercase literals; CSS adds bold and the active state."""
from __future__ import annotations

from html import escape
from typing import List

import streamlit as st

from auth.permissions import Permission, has_permission
from config import get_settings

NAV_ITEMS: List[str] = ["DASHBOARD", "DEPARTMENTS", "LECTURERS", "COURSES", "CLASSROOMS", "TIMETABLE",
                        "GENERATE TIMETABLE", "SETTINGS"]

NAV_PERMISSION = {
    "DASHBOARD": None, "SETTINGS": None,
    "DEPARTMENTS": Permission.VIEW_RECORDS, "LECTURERS": Permission.VIEW_RECORDS, "COURSES": Permission.VIEW_RECORDS,
    "CLASSROOMS": Permission.VIEW_RECORDS, "TIMETABLE": Permission.VIEW_PUBLISHED, "GENERATE TIMETABLE": Permission.GENERATE,
}


def visible_items(user) -> List[str]:
    return [i for i in NAV_ITEMS if NAV_PERMISSION[i] is None or has_permission(user, NAV_PERMISSION[i])]


def current_page(user=None) -> str:
    items = visible_items(user) if user is not None else NAV_ITEMS
    if "page" not in st.session_state:
        requested = st.query_params.get("page")
        st.session_state["page"] = requested if requested in items else items[0]
    if st.session_state["page"] not in items:
        st.session_state["page"] = items[0]
    return st.session_state["page"]


def go(page: str) -> None:
    st.session_state["page"] = page
    st.query_params["page"] = page


def render_sidebar(user) -> str:
    active = current_page(user)
    with st.sidebar:
        st.markdown(f'<div class="brand"><div class="brand-name">{escape(get_settings().app_name)}</div></div>',
                    unsafe_allow_html=True)
        for item in visible_items(user):
            st.button(item, key=f"nav_{item}", type="primary" if item == active else "secondary", width="stretch",
                      on_click=go, args=(item,))
    return active
