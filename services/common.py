"""Shared service-layer helpers and exceptions."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.permissions import PermissionDenied  # noqa: F401  (re-exported)


class ServiceError(Exception):
    """Base class for errors whose message is safe to show to users."""


class ValidationError(ServiceError):
    pass


class NotFoundError(ServiceError):
    pass


class DuplicateError(ValidationError):
    pass


class ConflictError(ServiceError):
    pass


@contextmanager
def integrity_guard(session: Session, message: str) -> Iterator[None]:
    """Translate database integrity errors into safe, meaningful messages."""
    try:
        with session.begin_nested():
            yield
            session.flush()
    except IntegrityError as exc:
        raise DuplicateError(message) from exc


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def clean(value: str | None) -> str:
    return (value or "").strip()


def require_text(value: str | None, label: str, max_len: int = 255) -> str:
    v = clean(value)
    if not v:
        raise ValidationError(f"{label} is required.")
    if len(v) > max_len:
        raise ValidationError(f"{label} must be at most {max_len} characters.")
    return v


def get_or_404(session: Session, model, pk, label: str = "Record"):
    obj = session.get(model, pk)
    if obj is None:
        raise NotFoundError(f"{label} was not found.")
    return obj


def utcnow() -> datetime:
    """Naive UTC timestamp (matches the naive DateTime columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
