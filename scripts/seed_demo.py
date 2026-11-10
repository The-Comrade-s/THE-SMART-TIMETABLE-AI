"""Optional demonstration data. Never runs automatically.

Usage:  python -m scripts.seed_demo --confirm [--size small|medium|large] [--session 2025/2026]
Demo records are marked DEMO / DEMONSTRATION RECORD. Refuses to run when APP_ENV=production.
"""
from __future__ import annotations

import argparse
import sys

from config import get_settings
from database import session_scope
from services.demo_data import SIZES, has_demo_data, seed_demo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="required: acknowledge that demo data will be inserted")
    ap.add_argument("--size", choices=list(SIZES), default="small")
    ap.add_argument("--session", default="2025/2026")
    args = ap.parse_args()
    if get_settings().app_env.lower() == "production":
        print("Refusing to seed demonstration data when APP_ENV=production.")
        return 1
    if not args.confirm:
        print("Add --confirm to insert clearly marked demonstration records.")
        return 1
    with session_scope() as s:
        if has_demo_data(s):
            print("Demonstration data already exists. Nothing was changed.")
            return 1
        result = seed_demo(s, args.size, args.session)
    print(f"Inserted demonstration data: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
