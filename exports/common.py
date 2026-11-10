from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.enums import DAYS
from database.models import Classroom, Department, Lecturer, StudentGroup, Timetable
from services.common import ValidationError
from services.settings_service import get_institution_name
from services.timetable_view import EntryView, load_entry_views

KINDS = ("university", "department", "group", "lecturer", "classroom")


@dataclass
class ExportContext:
    timetable: Timetable
    kind: str
    title: str
    subject: str
    institution: str
    entries: List[EntryView]
    status_note: str
    generated_on: str


def status_note(tt: Timetable) -> str:
    if tt.status == "PUBLISHED":
        return f"PUBLISHED timetable (version {tt.version})"
    note = f"{tt.status} timetable (version {tt.version}) - NOT PUBLISHED"
    if not tt.is_valid:
        note += " - CONTAINS UNRESOLVED HARD CONSTRAINT VIOLATIONS"
    return note


def build_context(session: Session, actor, timetable_id: int, kind: str = "university",
                  owner_id: Optional[int] = None) -> ExportContext:
    require(actor, Permission.EXPORT)
    if kind not in KINDS:
        raise ValidationError("Unknown export type.")
    kw, subject, title = {}, "All departments", "Complete University Timetable"
    if kind != "university":
        if owner_id is None:
            raise ValidationError("Select what to export.")
        model, key, label = {"department": (Department, "department_id", "Department"), "group": (StudentGroup, "group_id", "Student group"),
                             "lecturer": (Lecturer, "lecturer_id", "Lecturer"), "classroom": (Classroom, "room_id", "Classroom")}[kind]
        obj = session.get(model, owner_id)
        if obj is None:
            raise ValidationError(f"{label} was not found.")
        kw[key] = owner_id
        subject = {"department": lambda o: o.name, "group": lambda o: o.name, "lecturer": lambda o: o.full_name,
                   "classroom": lambda o: f"{o.building} {o.name}"}[kind](obj)
        title = f"{label} Timetable"
    entries = load_entry_views(session, actor, timetable_id, **kw)
    tt = session.get(Timetable, timetable_id)
    return ExportContext(tt, kind, title, subject, get_institution_name(session), entries, status_note(tt),
                         datetime.now().strftime("%d %B %Y %H:%M"))


def day_columns(entries: List[EntryView]) -> List[int]:
    used = sorted({e.day for e in entries})
    return sorted(set(range(5)) | set(used))
