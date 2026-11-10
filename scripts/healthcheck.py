"""Exit code 0 when the database is reachable and migrated. Usage: python -m scripts.healthcheck"""
import sys

from sqlalchemy import inspect

from database import get_engine, health_check


def main() -> int:
    state, msg = health_check()
    if state != "ok":
        print(f"database: {state} ({msg})")
        return 1
    tables = set(inspect(get_engine()).get_table_names())
    if "alembic_version" not in tables or "users" not in tables:
        print("database: reachable but not migrated (run: alembic upgrade head)")
        return 1
    print("database: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
