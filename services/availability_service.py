"""Weekly availability for lecturers and classrooms (same rules for both)."""
from __future__ import annotations

from datetime import time
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import Classroom, Lecturer, LecturerAvailability, RoomAvailability
from services.common import NotFoundError, ValidationError, get_or_404
from validation.rules import (to_minutes, validate_availability_status, validate_day, validate_interval)

Kind = Literal["lecturer", "room"]


def _cfg(kind: Kind):
    if kind == "lecturer":
        return LecturerAvailability, LecturerAvailability.lecturer_id, "lecturer_id", Lecturer
    return RoomAvailability, RoomAvailability.classroom_id, "classroom_id", Classroom


def list_availability(session: Session, actor, kind: Kind, owner_id: int):
    require(actor, Permission.VIEW_RECORDS)
    model, col, _, _ = _cfg(kind)
    return list(session.scalars(select(model).where(col == owner_id).order_by(model.day_of_week, model.start_time)))


def _check_overlap(session, kind, owner_id, day, start, end, exclude_id=None):
    for p in list_availability_unchecked(session, kind, owner_id):
        if p.id == exclude_id or p.day_of_week != day:
            continue
        if to_minutes(start) < to_minutes(p.end_time) and to_minutes(p.start_time) < to_minutes(end):
            raise ValidationError(f"This period overlaps an existing period ({p.start_time:%H:%M} to {p.end_time:%H:%M}) on the same day.")


def list_availability_unchecked(session: Session, kind: Kind, owner_id: int):
    model, col, _, _ = _cfg(kind)
    return list(session.scalars(select(model).where(col == owner_id)))


def add_availability(session: Session, actor, kind: Kind, owner_id: int, day: int, start: time, end: time,
                     status: str = "AVAILABLE"):
    require(actor, Permission.MANAGE_RECORDS)
    model, _, fk, owner_model = _cfg(kind)
    get_or_404(session, owner_model, owner_id, "Record")
    validate_day(day)
    validate_interval(start, end)
    validate_availability_status(status)
    _check_overlap(session, kind, owner_id, day, start, end)
    row = model(**{fk: owner_id}, day_of_week=day, start_time=start, end_time=end, status=status)
    session.add(row)
    session.flush()
    return row


def update_availability(session: Session, actor, kind: Kind, availability_id: int, day: int, start: time, end: time,
                        status: str):
    require(actor, Permission.MANAGE_RECORDS)
    model, _, fk, _ = _cfg(kind)
    row = session.get(model, availability_id)
    if row is None:
        raise NotFoundError("Availability period was not found.")
    validate_day(day)
    validate_interval(start, end)
    validate_availability_status(status)
    _check_overlap(session, kind, getattr(row, fk), day, start, end, exclude_id=row.id)
    row.day_of_week, row.start_time, row.end_time, row.status = day, start, end, status
    session.flush()
    return row


def remove_availability(session: Session, actor, kind: Kind, availability_id: int) -> None:
    require(actor, Permission.MANAGE_RECORDS)
    model, _, _, _ = _cfg(kind)
    row = session.get(model, availability_id)
    if row is None:
        raise NotFoundError("Availability period was not found.")
    session.delete(row)
    session.flush()
