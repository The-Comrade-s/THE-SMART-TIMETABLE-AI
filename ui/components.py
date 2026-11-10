"""Reusable presentational components. No emojis anywhere."""
from __future__ import annotations

from html import escape
from typing import Iterable, Sequence

import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    sub = f'<p class="page-sub">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(f'<h1 class="page-title">{escape(title)}</h1>{sub}', unsafe_allow_html=True)


def section_head(title: str, badge: str = "", badge_kind: str = "muted") -> None:
    b = f'<span class="badge badge-{badge_kind}">{escape(badge)}</span>' if badge else ""
    st.markdown(f'<div class="section-head"><h2>{escape(title)}</h2>{b}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, note: str = "") -> None:
    n = f'<div class="metric-note">{escape(note)}</div>' if note else ""
    st.markdown(
        f'<div class="card"><div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(str(value))}</div>{n}</div>',
        unsafe_allow_html=True,
    )


def notice(kind: str, message: str, heading: str = "") -> None:
    """kind: success | error | warning | info. Text labels are used, not colour alone."""
    labels = {"success": "Success", "error": "Error", "warning": "Warning", "info": "Note"}
    head = escape(heading or labels.get(kind, "Note"))
    st.markdown(
        f'<div class="notice notice-{kind}" role="status"><strong>{head}.</strong>{escape(message)}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str) -> None:
    st.markdown(
        f'<div class="empty"><div class="empty-title">{escape(title)}</div>'
        f'<div class="empty-body">{escape(body)}</div></div>',
        unsafe_allow_html=True,
    )


def status_badge(text: str, kind: str = "muted") -> str:
    return f'<span class="badge badge-{kind}">{escape(text)}</span>'


def data_table(columns: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    rows = list(rows)
    if not rows:
        empty_state("No records", "There is nothing to display yet.")
        return
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in rows
    )
    st.markdown(
        f'<div class="table-wrap"><table class="data"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )
