"""Service layer for system status. Pages call this instead of touching the database."""
from __future__ import annotations

from typing import Tuple

import streamlit as st

from database import health_check


@st.cache_data(ttl=15, show_spinner=False)
def database_status() -> Tuple[str, str]:
    return health_check()
