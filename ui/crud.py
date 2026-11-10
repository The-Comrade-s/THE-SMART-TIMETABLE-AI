"""Helpers shared by management pages."""
from __future__ import annotations

from typing import Callable, Optional

import streamlit as st

from algorithm.configuration import ConfigurationError
from auth.permissions import PermissionDenied
from auth.service import AuthenticationError
from database import session_scope
from services.common import ServiceError
from ui.components import notice
from ui.state import flash


def attempt(action: Callable, success: str, reset: Optional[str] = None) -> bool:
    """Run action(session) in one transaction. Show a clear message. Returns True on success."""
    from ui.state import reset_form
    try:
        with session_scope() as s:
            action(s)
    except (ServiceError, AuthenticationError, ConfigurationError) as exc:
        notice("error", str(exc))
        return False
    except PermissionDenied as exc:
        notice("error", str(exc), "Access denied")
        return False
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("Unexpected error")
        notice("error", "The operation could not be completed. Please try again.")
        return False
    flash("success", success)
    if reset:
        reset_form(reset)
    return True


def confirm_button(label: str, message: str, on_confirm: Callable[[], None], key: str, type_: str = "secondary") -> None:
    """Button that opens a confirmation dialog before running a consequential action."""
    @st.dialog("Confirm action")
    def _dialog():
        st.write(message)
        c1, c2 = st.columns(2)
        if c1.button("Confirm", key=f"{key}_yes", type="primary", width="stretch"):
            on_confirm()
            st.rerun()
        if c2.button("Cancel", key=f"{key}_no", width="stretch"):
            st.rerun()
    if st.button(label, key=key, type=type_):
        _dialog()


def options(items, label_fn, none_label: Optional[str] = None):
    """Return (labels, mapping label->id) for a selectbox."""
    mapping = {}
    if none_label:
        mapping[none_label] = None
    for it in items:
        mapping[label_fn(it)] = it.id
    return list(mapping.keys()), mapping
