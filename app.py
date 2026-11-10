"""Application entry point."""
from __future__ import annotations

import logging

import streamlit as st

from config import get_settings
from ui.components import notice
from ui.navigation import render_sidebar
from ui.state import current_user, render_flash, sign_out
from ui.theme import current_theme, init_theme, inject_css, toggle_theme
from views import login

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title=get_settings().app_name, page_icon=None, layout="wide", initial_sidebar_state="expanded")


def _top_bar(user) -> None:
    cols = st.columns([6, 1.2, 1.2] if user else [6, 1.4])
    with cols[-1 if not user else 1]:
        label = "Light mode" if current_theme() == "dark" else "Dark mode"
        st.button(label, key="theme_toggle", on_click=toggle_theme, width="stretch")
    if user:
        with cols[2]:
            if st.button("Sign out", key="top_signout", width="stretch"):
                sign_out()
                st.rerun()


def _page_registry():
    from views import classrooms, courses, dashboard, departments, generate, lecturers, settings, timetable
    return {"DASHBOARD": dashboard.render, "DEPARTMENTS": departments.render, "LECTURERS": lecturers.render,
            "COURSES": courses.render, "CLASSROOMS": classrooms.render, "TIMETABLE": timetable.render,
            "GENERATE TIMETABLE": generate.render, "SETTINGS": settings.render}


def main() -> None:
    init_theme()
    inject_css()
    user = current_user()
    if user is None:
        st.markdown("<style>section[data-testid='stSidebar']{display:none}</style>", unsafe_allow_html=True)
        _top_bar(None)
        login.render()
        return
    page = render_sidebar(user)
    _top_bar(user)
    render_flash()
    try:
        _page_registry()[page]()
    except Exception:  # noqa: BLE001
        logging.exception("Unhandled error rendering page %s", page)
        notice("error", "Something went wrong while loading this page. Please try again.", "Error")


main()
