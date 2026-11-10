"""PDF and Excel exports of an imported examination dataset (clearly labelled as a DRAFT source dataset)."""
from __future__ import annotations

import io
from typing import List, Optional
from xml.sax.saxutils import escape

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from exports.excel_export import _sheet
from exports.pdf_export import ALT, CELL, CELLB, GRID, H2, HEAD, HEAD_BG, NOTE, SUB, TITLE, _canvas_for, _p
from services import exam_service as ex
from services.common import ValidationError


def _context(session: Session, actor, dataset_id: int):
    require(actor, Permission.IMPORT_DATASETS)
    require(actor, Permission.EXPORT)
    ds = ex._exam_dataset(session, actor, dataset_id)
    return ds, ex.list_days(session, actor, dataset_id)


def export_exam_pdf(session: Session, actor, dataset_id: int, day_no: Optional[int] = None) -> bytes:
    ds, days = _context(session, actor, dataset_id)
    if day_no is not None and day_no not in {d.day_no for d in days}:
        raise ValidationError("That examination day is not in the dataset.")
    rows = ex.search_entries(session, actor, dataset_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                            title=ds.name)
    story = [Paragraph(escape(ds.name), TITLE), Paragraph(escape(f"Source document: {ds.source_document}"), SUB),
             Paragraph("DRAFT SOURCE DATASET - TEST DATA. Not an approved or final institutional timetable.", NOTE), Spacer(1, 3 * mm)]
    selected = [d for d in days if day_no is None or d.day_no == day_no]
    for n, d in enumerate(selected):
        if n:
            story.append(PageBreak())
        story.append(Paragraph(escape(f"Day {d.day_no}: {d.weekday}, {d.exam_date.strftime('%d %B %Y') if d.exam_date else d.date_text}"), H2))
        if d.faculty_group_text:
            story.append(Paragraph(escape(d.faculty_group_text), SUB))
        story.append(Spacer(1, 2 * mm))
        cols = []
        for s in d.sessions:
            cols.append([r for r in rows if r.day_no == d.day_no and r.slot_no == s.slot_no])
        head = [_p(f"{s.label_printed} ({len(cols[i])} examinations)", HEAD) for i, s in enumerate(d.sessions)]
        depth = max((len(c) for c in cols), default=0)
        data = [head]
        for i in range(depth):
            line = []
            for c in cols:
                if i < len(c):
                    r = c[i]
                    tag = f" [Batch {r.batch}]" if r.batch and f"Batch {r.batch}" not in r.course_title else ""
                    line.append(Paragraph(f"<b>{escape(r.course_code)}</b> {escape(r.course_title)}{escape(tag)}", CELL))
                else:
                    line.append("")
            data.append(line)
        width = (297 - 24) * mm / max(1, len(d.sessions))
        t = Table(data, colWidths=[width] * len(d.sessions), repeatRows=1)
        style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        style += [("BACKGROUND", (0, i), (-1, i), ALT) for i in range(2, len(data), 2)]
        t.setStyle(TableStyle(style))
        story.append(t)
    doc.build(story, canvasmaker=_canvas_for(f"{ds.name}  |  DRAFT SOURCE - TEST DATA"))
    return buf.getvalue()


def export_exam_excel(session: Session, actor, dataset_id: int) -> bytes:
    ds, days = _context(session, actor, dataset_id)
    rows = ex.search_entries(session, actor, dataset_id)
    wb = Workbook()
    headers = ["Day", "Date", "Weekday", "Session (as printed)", "Start", "Course code", "Course title", "Base code (reference)", "Batch",
               "NOUN prefix", "PDF page", "Faculty group", "Needs review", "Review reasons"]
    _sheet(wb, "ALL ENTRIES", headers,
           ([r.day_no, r.exam_date.isoformat() if r.exam_date else "", r.weekday, r.session_label, r.session_start.strftime("%H:%M"),
             r.course_code, r.course_title, r.base_code, r.batch or "", "Yes" if r.noun_prefixed else "No", r.page_no,
             r.faculty_group_code or "", "Yes" if r.needs_review else "No", "; ".join(r.review_reasons)] for r in rows), first=True)
    summary = []
    for d in days:
        for s in d.sessions:
            n = sum(1 for r in rows if r.day_no == d.day_no and r.slot_no == s.slot_no)
            summary.append([d.day_no, d.exam_date.isoformat() if d.exam_date else "", d.weekday, s.label_printed, s.start_time.strftime("%H:%M"), n, d.page_no])
    _sheet(wb, "BY DAY AND SESSION", ["Day", "Date", "Weekday", "Session (as printed)", "Start", "Examinations", "PDF page"], summary)
    rep = ds.report or {}
    items = [["Dataset", ds.name], ["Source document", ds.source_document], ["Status", "DRAFT SOURCE DATASET - TEST DATA"],
             ["Validation status", ds.validation_status]]
    for k in ("pages_total", "pages_processed", "days_identified", "sessions_identified", "entries_extracted", "unique_course_codes",
              "batch_a_entries", "batch_b_entries", "noun_prefixed_entries", "missing_course_codes", "missing_course_titles",
              "needs_manual_review", "imported", "duplicates_prevented", "independent_token_count"):
        if k in rep:
            items.append([k.replace("_", " ").capitalize(), rep[k]])
    _sheet(wb, "VALIDATION REPORT", ["Item", "Value"], items)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
