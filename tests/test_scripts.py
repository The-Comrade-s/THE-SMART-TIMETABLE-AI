import pytest
from sqlalchemy import select

from database.models import Department, User


def test_create_admin_script_once_only(db, monkeypatch):
    from scripts import create_admin
    monkeypatch.setenv("ADMIN_NAME", "Root"); monkeypatch.setenv("ADMIN_EMAIL", "root@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "StrongPass123")
    assert create_admin.main() == 0
    assert create_admin.main() == 1                     # second run refused
    from database import session_scope
    with session_scope() as s:
        assert s.scalar(select(User).where(User.email == "root@example.test")).role == "SUPER_ADMIN"


def test_seed_script_requires_confirm_refuses_production_and_dedupes(db, monkeypatch):
    from config import settings
    from scripts import seed_demo
    monkeypatch.setattr("sys.argv", ["seed"])
    assert seed_demo.main() == 1                        # no --confirm
    monkeypatch.setattr("sys.argv", ["seed", "--confirm"])
    assert seed_demo.main() == 0
    assert seed_demo.main() == 1                        # already seeded
    from database import session_scope
    with session_scope() as s:
        codes = [d.code for d in s.scalars(select(Department))]
        assert codes and all(c.startswith("DEMO") for c in codes)
        assert all("DEMONSTRATION" in (d.description or "") for d in s.scalars(select(Department)))
    monkeypatch.setenv("APP_ENV", "production"); settings.get_settings.cache_clear()
    assert seed_demo.main() == 1
    settings.get_settings.cache_clear()


def test_healthcheck_script(db):
    from scripts import healthcheck
    assert healthcheck.main() == 0


def test_time_slot_service(session, super_admin, admin):
    from datetime import time
    from auth.permissions import PermissionDenied
    from services import time_slot_service as ts
    with pytest.raises(PermissionDenied):
        ts.generate_slots(session, admin, [0], time(8), time(12))
    assert ts.generate_slots(session, super_admin, [0, 1], time(8), time(12), 60) == 8
    assert ts.generate_slots(session, super_admin, [0, 1], time(8), time(12), 60) == 0       # idempotent
    from services.common import ValidationError
    for args in (([], time(8), time(12), 60), ([0], time(12), time(8), 60), ([0], time(8), time(12), 5)):
        with pytest.raises(ValidationError):
            ts.generate_slots(session, super_admin, *args)
    slot = ts.list_time_slots(session, super_admin)[0]
    ts.set_slot_active(session, super_admin, slot.id, False)
    assert not session.get(type(slot), slot.id).is_active
    assert ts.generate_slots(session, super_admin, [2], time(9), time(11), 30, replace=True) == 4


def test_institution_name_setting(session, super_admin, admin):
    from auth.permissions import PermissionDenied
    from services import settings_service as ss
    with pytest.raises(PermissionDenied):
        ss.set_institution_name(session, admin, "X")
    ss.set_institution_name(session, super_admin, "Federal Polytechnic")
    assert ss.get_institution_name(session) == "Federal Polytechnic"
