"""Streamlit session helpers: authenticated user, flash messages, form resets."""
from __future__ import annotations

from typing import Optional

import streamlit as st

from auth import service as auth_service
from database import session_scope
from database.models import User


def current_user() -> Optional[User]:
    """Validate the server-side session on every run (so deactivation or expiry takes effect immediately)."""
    token = st.session_state.get("auth_token")
    if not token:
        return None
    try:
        with session_scope() as s:
            user = auth_service.validate_session(s, token)
    except Exception:  # noqa: BLE001
        return None
    if user is None:
        for k in ("auth_token", "user"):
            st.session_state.pop(k, None)
        return None
    st.session_state["user"] = user
    return user


def sign_in(user: User, token: str) -> None:
    st.session_state["auth_token"] = token
    st.session_state["user"] = user


def sign_out() -> None:
    token = st.session_state.get("auth_token")
    try:
        with session_scope() as s:
            auth_service.logout(s, token)
    finally:
        for k in list(st.session_state.keys()):
            if k not in ("theme",):
                del st.session_state[k]


def flash(kind: str, message: str) -> None:
    st.session_state.setdefault("_flash", []).append((kind, message))


def render_flash() -> None:
    from ui.components import notice
    for kind, msg in st.session_state.pop("_flash", []):
        notice(kind, msg)


def form_key(name: str) -> str:
    """Key that changes after every successful submission (clears the form, prevents double submits)."""
    return f"{name}_{st.session_state.get(f'_n_{name}', 0)}"


def reset_form(name: str) -> None:
    st.session_state[f"_n_{name}"] = st.session_state.get(f"_n_{name}", 0) + 1
