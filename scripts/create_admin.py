"""Controlled first-administrator setup.

Usage:  python -m scripts.create_admin
Works only while no SUPER_ADMIN exists. The password is read with getpass (never echoed, never logged)
or from the ADMIN_PASSWORD environment variable for non-interactive deployments.
"""
from __future__ import annotations

import getpass
import os
import sys

from auth import service
from database import session_scope
from services.common import ServiceError


def main() -> int:
    try:
        with session_scope() as s:
            if service.count_super_admins(s) > 0:
                print("An administrator already exists. Initial setup is disabled.")
                return 1
    except Exception:  # noqa: BLE001
        print("Cannot reach the database. Check DATABASE_URL and run the migrations first (alembic upgrade head).")
        return 2
    name = os.getenv("ADMIN_NAME") or input("Full name: ").strip()
    email = os.getenv("ADMIN_EMAIL") or input("Email address: ").strip()
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords do not match.")
            return 1
    try:
        with session_scope() as s:
            service.create_first_admin(s, name, email, password)
    except ServiceError as exc:
        print(f"Setup failed: {exc}")
        return 1
    print("Super admin created. You can now sign in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
