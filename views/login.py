from __future__ import annotations

from html import escape

import streamlit as st

from auth import service as auth_service
from config import get_settings
from database import session_scope
from services.common import ServiceError
from services.system_status import database_status
from ui.components import notice
from ui.state import sign_in


def render() -> None:
    s = get_settings()
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown(f'<div class="login-brand"><h1>{escape(s.app_name)}</h1><p class="page-sub">Sign in to continue</p></div>', unsafe_allow_html=True)
        state, msg = database_status()
        if state != "ok":
            notice("error", f"{msg}. Sign-in is unavailable until the database is reachable.", "Database")
            return
        with st.form("login_form"):
            email = st.text_input("Email address", key="login_email", autocomplete="username")
            password = st.text_input("Password", type="password", key="login_password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            if not email.strip() or not password:
                notice("error", "Enter both your email address and password.")
                return
            try:
                with st.spinner("Signing in"):
                    with session_scope() as db:
                        user, token = auth_service.authenticate(db, email, password)
                sign_in(user, token)
                st.rerun()
            except ServiceError as exc:
                notice("error", str(exc))
            except Exception:  # noqa: BLE001
                notice("error", "Sign-in is temporarily unavailable. Please try again.")
