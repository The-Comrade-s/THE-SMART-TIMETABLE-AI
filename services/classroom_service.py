from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from database.models import Classroom
from services.common import ValidationError, clean, escape_like, get_or_404, integrity_guard, require_text
from validation.rules import validate_positive_int, validate_room_type


def _fields(name, building, capacity, room_type, description):
    return dict(name=require_text(name, "Room name", 80), building=require_text(building, "Building", 120),
                capacity=validate_positive_int(capacity, "Room capacity", 5000), room_type=validate_room_type(room_type),
                description=clean(description) or None)


def _dup(session, data, exclude_id=None):
    q = select(Classroom.id).where(func.lower(Classroom.name) == data["name"].lower(),
                                   func.lower(Classroom.building) == data["building"].lower())
    if exclude_id:
        q = q.where(Classroom.id != exclude_id)
    if session.scalar(q) is not None:
        raise ValidationError(f"A room named {data['name']} already exists in {data['building']}.")


def create_classroom(session: Session, actor, name, building, capacity, room_type, description="") -> Classroom:
    require(actor, Permission.MANAGE_RECORDS)
    data = _fields(name, building, capacity, room_type, description)
    _dup(session, data)
    room = Classroom(**data)
    with integrity_guard(session, f"A room named {data['name']} already exists in {data['building']}."):
        session.add(room)
    return room


def update_classroom(session: Session, actor, room_id: int, name, building, capacity, room_type, description="",
                     is_available: bool = True) -> Classroom:
    require(actor, Permission.MANAGE_RECORDS)
    room = get_or_404(session, Classroom, room_id, "Classroom")
    data = _fields(name, building, capacity, room_type, description)
    _dup(session, data, room_id)
    with integrity_guard(session, f"A room named {data['name']} already exists in {data['building']}."):
        for k, v in data.items():
            setattr(room, k, v)
        room.is_available = bool(is_available)
    return room


def set_classroom_status(session: Session, actor, room_id: int, active: bool) -> Classroom:
    require(actor, Permission.MANAGE_RECORDS)
    room = get_or_404(session, Classroom, room_id, "Classroom")
    room.status = "ACTIVE" if active else "INACTIVE"
    session.flush()
    return room


def list_classrooms(session: Session, actor, search: str = "", building: Optional[str] = None,
                    room_type: Optional[str] = None, available: Optional[bool] = None,
                    status: Optional[str] = None) -> list[Classroom]:
    require(actor, Permission.VIEW_RECORDS)
    q = select(Classroom).order_by(Classroom.building, Classroom.name)
    if search.strip():
        like = f"%{escape_like(search.strip().lower())}%"
        q = q.where(or_(func.lower(Classroom.name).like(like, escape="\\"), func.lower(Classroom.building).like(like, escape="\\")))
    if building:
        q = q.where(Classroom.building == building)
    if room_type:
        q = q.where(Classroom.room_type == room_type)
    if available is not None:
        q = q.where(Classroom.is_available == available)
    if status:
        q = q.where(Classroom.status == status)
    return list(session.scalars(q))


def list_buildings(session: Session, actor) -> list[str]:
    require(actor, Permission.VIEW_RECORDS)
    return list(session.scalars(select(Classroom.building).distinct().order_by(Classroom.building)))
