import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def db(tmp_path):
    """Isolated SQLite database per test, schema created by Alembic migrations."""
    from alembic import command
    from alembic.config import Config
    import database.models  # noqa: F401
    from database import connection

    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    if url.startswith("postgresql"):      # real PostgreSQL: start every test from an empty schema
        from sqlalchemy import create_engine, text
        eng = create_engine(url)
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        eng.dispose()
    os.environ["ALEMBIC_DATABASE_URL"] = url
    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations"))
    command.upgrade(cfg, "head")
    connection.configure(url)
    yield url
    connection.reset()
    os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture()
def session(db):
    from database import session_scope
    with session_scope() as s:
        yield s


def _make_user(session, role, email):
    from auth.service import _create_user
    u = _create_user(session, f"Test {role}", email, "StrongPass123", role)
    session.commit()
    return u


@pytest.fixture()
def super_admin(session):
    return _make_user(session, "SUPER_ADMIN", "super@example.test")


@pytest.fixture()
def admin(session):
    return _make_user(session, "ADMIN", "admin@example.test")


@pytest.fixture()
def viewer(session):
    return _make_user(session, "VIEWER", "viewer@example.test")


@pytest.fixture()
def demo(session, super_admin):
    from services.demo_data import seed_demo
    seed_demo(session, "small")
    session.commit()
    return session
