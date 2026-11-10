from __future__ import annotations

from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import TimeSlot
from services.common import ValidationError
from validation.rules import from_minutes, to_minutes, validate_interval


def list_time_slots(session: Session, actor):
    require(actor, Permission.VIEW_RECORDS)
    return list(session.scalars(select(TimeSlot).order_by(TimeSlot.day_of_week, TimeSlot.start_time)))


def generate_slots(session: Session, actor, days, start: time, end: time, slot_minutes: int = 60,
                   replace: bool = False) -> int:
    """Create contiguous slots (e.g. hourly 08:00-18:00) for the given weekdays."""
    require(actor, Permission.MANAGE_SETTINGS)
    validate_interval(start, end, "Teaching hours")
    if slot_minutes < 15 or slot_minutes > 240:
        raise ValidationError("Slot length must be between 15 and 240 minutes.")
    if not days:
        raise ValidationError("Select at least one teaching day.")
    if replace:
        session.execute(delete(TimeSlot))
    created = 0
    existing = {(s.day_of_week, s.start_time, s.end_time) for s in session.scalars(select(TimeSlot))}
    for d in days:
        t = to_minutes(start)
        while t + slot_minutes <= to_minutes(end):
            key = (d, from_minutes(t), from_minutes(t + slot_minutes))
            if key not in existing:
                session.add(TimeSlot(day_of_week=d, start_time=key[1], end_time=key[2], duration_minutes=slot_minutes,
                                     is_active=True))
                created += 1
            t += slot_minutes
    session.flush()
    return created


def set_slot_active(session: Session, actor, slot_id: int, active: bool) -> None:
    require(actor, Permission.MANAGE_SETTINGS)
    slot = session.get(TimeSlot, slot_id)
    if slot is None:
        raise ValidationError("Time slot was not found.")
    slot.is_active = active
    session.flush()
