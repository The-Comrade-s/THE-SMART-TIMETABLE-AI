"""Consistent data table: sorting, pagination, record counts and empty states."""
from __future__ import annotations

from html import escape
from typing import Sequence

import streamlit as st

from ui.components import empty_state


class Badge:
    def __init__(self, text: str, kind: str = "muted"):
        self.text, self.kind = text, kind

    def html(self) -> str:
        return f'<span class="badge badge-{self.kind}">{escape(self.text)}</span>'


def status_badge(status: str) -> Badge:
    kind = {"ACTIVE": "ok", "PUBLISHED": "ok", "APPROVED": "ok", "VALIDATED": "ok", "COMPLETED": "ok",
            "INACTIVE": "muted", "ARCHIVED": "muted", "DRAFT": "sample", "GENERATED": "sample",
            "FAILED": "error", "INTERRUPTED": "sample"}.get(status, "muted")
    return Badge(status.title().replace("_", " "), kind)


def _plain(v) -> str:
    return v.text if isinstance(v, Badge) else str(v)


def paginated_table(key: str, columns: Sequence[str], rows: Sequence[Sequence], page_size: int = 10,
                    empty_title: str = "No records found", empty_body: str = "Adjust the search or filters, or add a record.") -> None:
    total = len(rows)
    if total == 0:
        empty_state(empty_title, empty_body)
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        sort_col = st.selectbox("Sort by", ["Default"] + list(columns), key=f"{key}_sort")
    with c2:
        desc = st.toggle("Descending", key=f"{key}_desc")
    pages = max(1, -(-total // page_size))
    with c3:
        page = st.number_input("Page", 1, pages, 1, key=f"{key}_page", disabled=pages == 1)
    data = list(rows)
    if sort_col != "Default":
        idx = list(columns).index(sort_col)
        def sk(r):
            v = _plain(r[idx])
            try:
                return (0, float(v), "")
            except ValueError:
                return (1, 0.0, v.lower())
        data.sort(key=sk, reverse=desc)
    start = (int(page) - 1) * page_size
    chunk = data[start:start + page_size]
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{c.html() if isinstance(c, Badge) else escape(str(c))}</td>" for c in r) + "</tr>"
                   for r in chunk)
    st.markdown(f'<div class="table-wrap"><table class="data"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption(f"Showing {start + 1} to {start + len(chunk)} of {total} records")
