"""Excel exports (OpenPyXL)."""
from __future__ import annotations

import io
from typing import Iterable, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import GenerationHistory
from exports.common import ExportContext, build_context
from services.timetable_view import EntryView

HEAD_FILL = PatternFill("solid", start_color="1F3A68")
HEAD_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="B8C2D6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COLS = ["Day", "Start", "End", "Course code", "Course title", "Lecturer", "Classroom", "Student group", "Department", "Level"]


def _row(e: EntryView) -> list:
    return [e.day_name, f"{e.start // 60:02d}:{e.start % 60:02d}", f"{e.end // 60:02d}:{e.end % 60:02d}", e.course_code,
            e.course_title, e.lecturer, e.room, e.group, e.department, e.level]


def _sheet(wb: Workbook, title: str, headers: Sequence[str], rows: Iterable[Sequence], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws.append(list(headers))
    count = 0
    for r in rows:
        ws.append(list(r))
        count += 1
    for c in ws[1]:
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.border = BORDER
            c.alignment = Alignment(vertical="top", wrap_text=True)
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(ws.cell(row=r, column=i).value or "")) for r in range(2, min(ws.max_row, 300) + 1)])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 3, 10), 48)
    ws.freeze_panes = "A2"
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions
    ws.page_setup.orientation, ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = "landscape", 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"
    return ws


def _summary_rows(ctx: ExportContext, hist) -> List[list]:
    tt = ctx.timetable
    rows = [["Institution", ctx.institution], ["Timetable", tt.name], ["Version", tt.version], ["Status", tt.status],
            ["Academic session", tt.academic_session], ["Semester", tt.semester.title()],
            ["Department scope", tt.department.name if tt.department else "All departments"],
            ["Independent validation", "No hard violations" if tt.is_valid else f"{tt.hard_violations} hard violations"],
            ["Fitness score", tt.fitness_score], ["Soft penalty", tt.soft_penalty], ["Sessions scheduled", len(ctx.entries)],
            ["Note", ctx.status_note]]
    if hist:
        rows += [["Initial fitness", hist.initial_fitness], ["Final fitness", hist.final_fitness], ["Generations", hist.generations],
                 ["Best generation", hist.best_generation], ["Execution seconds", hist.execution_seconds],
                 ["Termination reason", hist.termination_reason]]
    return rows


def export_timetable_excel(session: Session, actor, timetable_id: int, kind: str = "university", owner_id=None) -> bytes:
    ctx = build_context(session, actor, timetable_id, kind, owner_id)
    wb = Workbook()
    entries = ctx.entries
    if kind == "university":
        _sheet(wb, "TIMETABLE OVERVIEW", COLS, (_row(e) for e in entries), first=True)
        _sheet(wb, "DEPARTMENT SCHEDULES", ["Department"] + COLS, (([e.department] + _row(e)) for e in sorted(entries, key=lambda x: (x.department, x.day, x.start))))
        _sheet(wb, "LECTURER SCHEDULES", ["Lecturer"] + COLS, (([e.lecturer] + _row(e)) for e in sorted(entries, key=lambda x: (x.lecturer, x.day, x.start))))
        _sheet(wb, "CLASSROOM SCHEDULES", ["Classroom"] + COLS, (([e.room] + _row(e)) for e in sorted(entries, key=lambda x: (x.room, x.day, x.start))))
        _sheet(wb, "STUDENT GROUP SCHEDULES", ["Student group"] + COLS, (([e.group] + _row(e)) for e in sorted(entries, key=lambda x: (x.group, x.day, x.start))))
        hist = session.scalar(select(GenerationHistory).where(GenerationHistory.timetable_id == timetable_id).order_by(GenerationHistory.id.desc())) \
            if _can_history(actor) else None
        _sheet(wb, "GENERATION SUMMARY", ["Item", "Value"], _summary_rows(ctx, hist))
    else:
        _sheet(wb, "SCHEDULE", COLS, (_row(e) for e in entries), first=True)
        _sheet(wb, "DETAILS", ["Item", "Value"], _summary_rows(ctx, None) + [["Export subject", ctx.subject]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _can_history(actor) -> bool:
    from auth.permissions import has_permission
    return has_permission(actor, Permission.VIEW_HISTORY)
