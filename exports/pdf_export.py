"""PDF exports (ReportLab): timetables and the generation report."""
from __future__ import annotations

import io
from math import gcd
from typing import List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape

from auth.permissions import Permission, require
from database.enums import DAYS
from database.models import GenerationHistory, Timetable
from exports.common import ExportContext, build_context, day_columns
from services.timetable_service import get_timetable
from services.timetable_view import EntryView

NAVY, GRID, HEAD_BG, ALT = colors.HexColor("#0F1B33"), colors.HexColor("#8A97B0"), colors.HexColor("#E3E9F5"), colors.HexColor("#F5F7FB")

_ss = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=_ss["Title"], fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=2, alignment=0)
SUB = ParagraphStyle("s", parent=_ss["Normal"], fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#3B4760"))
CELL = ParagraphStyle("c", parent=_ss["Normal"], fontName="Helvetica", fontSize=7.5, leading=9)
CELLB = ParagraphStyle("cb", parent=CELL, fontName="Helvetica-Bold")
HEAD = ParagraphStyle("h", parent=CELL, fontName="Helvetica-Bold", fontSize=8, textColor=NAVY, alignment=TA_CENTER)
NOTE = ParagraphStyle("n", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#8A1C1C"))
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=NAVY)


class _NumberedCanvas(canvas.Canvas):
    footer_text = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            w, _ = self._pagesize
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#55627D"))
            self.drawString(15 * mm, 9 * mm, self.footer_text)
            self.drawRightString(w - 15 * mm, 9 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _canvas_for(footer: str):
    return type("FooterCanvas", (_NumberedCanvas,), {"footer_text": footer})


def _p(text: str, style=CELL) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _header(ctx: ExportContext) -> list:
    tt = ctx.timetable
    dept = tt.department.name if tt.department else "All departments"
    meta = [[_p("Institution", CELLB), _p(ctx.institution), _p("Academic session", CELLB), _p(tt.academic_session)],
            [_p("Department scope", CELLB), _p(dept), _p("Semester", CELLB), _p(tt.semester.title())],
            [_p("Timetable", CELLB), _p(tt.name), _p("Subject", CELLB), _p(ctx.subject)],
            [_p("Generated", CELLB), _p(tt.generated_at.strftime("%d %B %Y")), _p("Exported", CELLB), _p(ctx.generated_on)]]
    t = Table(meta, colWidths=[28 * mm, 85 * mm, 32 * mm, 85 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (0, -1), HEAD_BG),
                           ("BACKGROUND", (2, 0), (2, -1), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    out = [Paragraph(escape(ctx.title), TITLE), Paragraph(escape(ctx.subject), SUB), Spacer(1, 3 * mm), t, Spacer(1, 2 * mm),
           Paragraph(escape(ctx.status_note), NOTE if ctx.timetable.status != "PUBLISHED" else SUB), Spacer(1, 3 * mm)]
    return out


def _list_table(entries: List[EntryView]) -> Table:
    head = ["Day", "Time", "Code", "Course title", "Lecturer", "Classroom", "Group"]
    rows = [[_p(h, HEAD) for h in head]]
    for e in entries:
        rows.append([_p(e.day_name), _p(e.time_label), _p(e.course_code, CELLB), _p(e.course_title), _p(e.lecturer),
                     _p(e.room), _p(e.group)])
    if len(rows) == 1:
        rows.append([_p("No sessions scheduled."), "", "", "", "", "", ""])
    t = Table(rows, colWidths=[22 * mm, 28 * mm, 24 * mm, 70 * mm, 45 * mm, 42 * mm, 36 * mm], repeatRows=1)
    style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for i in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), ALT))
    t.setStyle(TableStyle(style))
    return t


def _grid_table(entries: List[EntryView], show_group: bool, show_lecturer: bool, show_room: bool) -> Table:
    days = day_columns(entries)
    if not entries:
        return Table([[_p("No sessions scheduled.")]])
    t0, t1 = min(e.start for e in entries), max(e.end for e in entries)
    step = 60
    for e in entries:
        step = gcd(step, gcd(e.start, e.end))
    t0 = (t0 // 60) * 60
    rows_t = list(range(t0, t1, step))
    head = [_p("Time", HEAD)] + [_p(DAYS[d], HEAD) for d in days]
    data = [head] + [[_p(f"{m // 60:02d}:{m % 60:02d}", CELLB)] + [""] * len(days) for m in rows_t]
    spans, covered = [], set()
    for ci, d in enumerate(days, start=1):
        col = [e for e in entries if e.day == d]
        for e in col:
            r0 = (e.start - t0) // step
            nrows = max(1, (e.end - e.start) // step)
            clash = [o for o in col if o is not e and o.start < e.end and e.start < o.end]
            parts = [f"<b>{escape(e.course_code)}</b>", escape(e.course_title)]
            if show_lecturer:
                parts.append(escape(e.lecturer))
            if show_room:
                parts.append(escape(e.room))
            if show_group:
                parts.append(escape(e.group))
            parts.append(escape(e.time_label))
            cell = Paragraph("<br/>".join(parts), CELL)
            cur = data[1 + r0][ci]
            data[1 + r0][ci] = [cur, cell] if cur != "" else cell
            if not clash and nrows > 1:
                spans.append(("SPAN", (ci, 1 + r0), (ci, r0 + nrows)))
    t = Table(data, colWidths=[16 * mm] + [(267 * mm - 16 * mm) / len(days)] * len(days), repeatRows=1)
    style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("BACKGROUND", (0, 1), (0, -1), HEAD_BG),
             ("VALIGN", (0, 0), (-1, -1), "TOP")] + spans
    t.setStyle(TableStyle(style))
    return t


def export_timetable_pdf(session: Session, actor, timetable_id: int, kind: str = "university", owner_id=None) -> bytes:
    ctx = build_context(session, actor, timetable_id, kind, owner_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=ctx.title, author=ctx.institution)
    story = _header(ctx)
    if kind == "university":
        story.append(_list_table(ctx.entries))
    elif kind == "department":
        story.append(_list_table(ctx.entries))
    else:
        story.append(_grid_table(ctx.entries, show_group=kind != "group", show_lecturer=kind != "lecturer", show_room=kind != "classroom"))
        story += [Spacer(1, 4 * mm), Paragraph("Session list", H2), _list_table(ctx.entries)]
    footer = f"{ctx.institution}  |  {ctx.timetable.name}  |  {ctx.timetable.status}"
    doc.build(story, canvasmaker=_canvas_for(footer))
    return buf.getvalue()


def export_generation_report_pdf(session: Session, actor, timetable_id: int) -> bytes:
    require(actor, Permission.EXPORT)
    require(actor, Permission.VIEW_HISTORY)
    tt = get_timetable(session, actor, timetable_id)
    ctx = build_context(session, actor, timetable_id)
    hist = session.scalar(select(GenerationHistory).where(GenerationHistory.timetable_id == timetable_id)
                          .order_by(GenerationHistory.id.desc()))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Timetable generation report")
    story = [Paragraph("Timetable Generation Report", TITLE), Paragraph(escape(ctx.institution), SUB), Spacer(1, 4 * mm)]

    def table(rows, widths=(70 * mm, 100 * mm)):
        t = Table([[_p(a, CELLB), _p(b)] for a, b in rows], colWidths=list(widths))
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (0, -1), HEAD_BG)]))
        return t

    story += [Paragraph("Timetable", H2), table([
        ("Name", tt.name), ("Version", tt.version), ("Academic session", tt.academic_session), ("Semester", tt.semester.title()),
        ("Department scope", tt.department.name if tt.department else "All departments"), ("Status", tt.status),
        ("Independent validation", "No hard constraint violations" if tt.is_valid else f"{tt.hard_violations} hard constraint violations (NOT conflict-free)")])]
    if hist is None:
        story += [Spacer(1, 4 * mm), Paragraph("No generation history is stored for this timetable (for example, a copied revision).", SUB)]
    else:
        imp = ((hist.final_fitness - hist.initial_fitness) / hist.initial_fitness * 100) if hist.initial_fitness else 0.0
        p = hist.parameters or {}
        story += [Spacer(1, 4 * mm), Paragraph("Optimisation", H2), table([
            ("Initial fitness", f"{hist.initial_fitness:.6f}"), ("Final fitness", f"{hist.final_fitness:.6f}"),
            ("Improvement", f"{imp:.1f}%"), ("Generations executed", hist.generations), ("Best generation", hist.best_generation),
            ("Execution time", f"{hist.execution_seconds:.2f} s"), ("Termination reason", hist.termination_reason),
            ("Run status", hist.status)]),
            Spacer(1, 4 * mm), Paragraph("Algorithm configuration", H2),
            table([(k.replace("_", " ").capitalize(), v) for k, v in p.items() if k not in ("hard_weights", "soft_weights", "seed")])]
        br = hist.constraint_breakdown or {}
        story += [Spacer(1, 4 * mm), Paragraph("Constraint evaluation (Genetic Algorithm)", H2),
                  table([(k, v) for k, v in (br.get("hard") or {}).items()] + [(k, v) for k, v in (br.get("soft") or {}).items()])]
    footer = f"{ctx.institution}  |  Generation report  |  {tt.name}"
    doc.build(story, canvasmaker=_canvas_for(footer))
    return buf.getvalue()
