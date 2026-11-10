from __future__ import annotations

from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from config import get_settings
from database.models import AppSetting
from services.common import require_text


def get_institution_name(session: Session) -> str:
    row = session.get(AppSetting, "institution_name")
    return row.value if row else get_settings().institution_name


def set_institution_name(session: Session, actor, name: str) -> str:
    require(actor, Permission.MANAGE_SETTINGS)
    name = require_text(name, "Institution name", 200)
    row = session.get(AppSetting, "institution_name")
    if row:
        row.value = name
    else:
        session.add(AppSetting(key="institution_name", value=name))
    session.flush()
    return name
