"""Weekly timetable grid: days as columns, time as rows, sessions as positioned blocks.

Overlapping sessions are laid out side by side (lanes) so none is hidden. Conflicting sessions carry a
visible CONFLICT label and a heavy border in addition to colour.
"""
from __future__ import annotations

from html import escape
from typing import Iterable, List, Set

import streamlit as st

from database.enums import DAYS
from services.timetable_view import EntryView, assign_lanes

PX_PER_MIN = 1.15
PALETTE = ["#2563EB", "#0891B2", "#7C3AED", "#D97706", "#059669", "#DB2777", "#4F46E5", "#65A30D"]


def _colour(code: str) -> str:
    return PALETTE[sum(ord(c) for c in code) % len(PALETTE)]


def render_grid(entries: List[EntryView], conflict_ids: Set[int] = frozenset(), days: Iterable[int] = range(5)) -> None:
    if not entries:
        from ui.components import empty_state
        empty_state("No sessions to display", "There are no scheduled sessions for this selection.")
        return
    days = sorted(set(days) | {e.day for e in entries})
    t0 = (min(e.start for e in entries) // 60) * 60
    t1 = -(-max(e.end for e in entries) // 60) * 60
    height = (t1 - t0) * PX_PER_MIN
    placed = assign_lanes(entries)
    axis = "".join(f'<div class="tt-hour" style="top:{(m - t0) * PX_PER_MIN}px">{m // 60:02d}:00</div>' for m in range(t0, t1, 60))
    cols = []
    for d in days:
        blocks = []
        for v, lane, n in (p for p in placed if p[0].day == d):
            top, h = (v.start - t0) * PX_PER_MIN, (v.end - v.start) * PX_PER_MIN - 3
            width, left = 100 / n, 100 / n * lane
            bad = v.entry_id in conflict_ids
            label = '<span class="tt-conflict">CONFLICT</span>' if bad else ""
            tip = escape(f"{v.course_code} {v.course_title} | {v.lecturer} | {v.room} | {v.group} | {v.time_label}")
            blocks.append(
                f'<div class="tt-block{" tt-bad" if bad else ""}" title="{tip}" style="top:{top}px;height:{h}px;'
                f'left:calc({left}% + 2px);width:calc({width}% - 4px);border-left-color:{_colour(v.course_code)}">'
                f'{label}<b>{escape(v.course_code)}</b><span>{escape(v.course_title)}</span>'
                f'<span>{escape(v.lecturer)}</span><span>{escape(v.room)}</span><span>{escape(v.group)}</span>'
                f'<span>{escape(v.time_label)}</span></div>')
        cols.append(f'<div class="tt-col"><div class="tt-dayhead">{DAYS[d]}</div><div class="tt-day" style="height:{height}px">'
                    f'{"".join(blocks)}</div></div>')
    html = (f'<div class="tt-wrap"><div class="tt-grid"><div class="tt-axis"><div class="tt-dayhead">Time</div>'
            f'<div class="tt-day" style="height:{height}px">{axis}</div></div>{"".join(cols)}</div></div>')
    st.markdown(html, unsafe_allow_html=True)


def entry_detail(v: EntryView, conflict: bool = False) -> None:
    st.markdown(
        f'<div class="card"><div class="metric-label">{escape(v.day_name)} {escape(v.time_label)}</div>'
        f'<div class="metric-value" style="font-size:1.25rem">{escape(v.course_code)} - {escape(v.course_title)}</div>'
        f'<div class="metric-note">Lecturer: {escape(v.lecturer)}<br>Classroom: {escape(v.room)}<br>Student group: {escape(v.group)} '
        f'(level {v.level})<br>Department: {escape(v.department)}<br>Session {v.session_no}'
        f'{"<br><b>This session is part of a hard constraint conflict.</b>" if conflict else ""}</div></div>', unsafe_allow_html=True)
