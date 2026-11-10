"""Authentication, session management and user administration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.permissions import Permission, require
from auth.security import (hash_password, hash_token, needs_rehash, new_token, password_policy_errors,
                           verify_password)
from database.enums import ROLES
from database.models import User, UserSession
from services.common import DuplicateError, NotFoundError, utcnow, ServiceError, ValidationError, integrity_guard, require_text
from validation.rules import validate_email

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
SESSION_HOURS = 8
GENERIC_LOGIN_ERROR = "Invalid email or password."


class AuthenticationError(ServiceError):
    pass


def _now() -> datetime:
    return utcnow()


def authenticate(session: Session, email: str, password: str) -> Tuple[User, str]:
    """Verify credentials and open a server-side session. Returns (user, raw_token)."""
    email = (email or "").strip().lower()
    if not email or not password:
        raise AuthenticationError("Enter your email and password.")
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21l$" + "A" * 43)  # equalise timing
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    if user.locked_until and user.locked_until > _now():
        raise AuthenticationError("Too many failed attempts. Try again later.")
    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_attempts = 0
        session.commit()
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    if user.status != "ACTIVE":
        raise AuthenticationError("This account is inactive. Contact an administrator.")
    user.failed_attempts, user.locked_until, user.last_login = 0, None, _now()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token = new_token()
    session.add(UserSession(user_id=user.id, token_hash=hash_token(token), created_at=_now(),
                            expires_at=_now() + timedelta(hours=SESSION_HOURS)))
    session.commit()
    return user, token


def validate_session(session: Session, token: Optional[str]) -> Optional[User]:
    """Return the active user for a valid, unexpired, unrevoked session; otherwise None."""
    if not token:
        return None
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.revoked or row.expires_at <= _now():
        return None
    user = session.get(User, row.user_id)
    if user is None or user.status != "ACTIVE":
        return None
    return user


def session_info(session: Session, token: str) -> Optional[UserSession]:
    return session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))


def logout(session: Session, token: Optional[str]) -> None:
    if not token:
        return
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is not None:
        row.revoked = True
        session.commit()


def count_super_admins(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == "SUPER_ADMIN")) or 0


def create_first_admin(session: Session, full_name: str, email: str, password: str) -> User:
    """Controlled setup: only works while no SUPER_ADMIN exists. Called from scripts/create_admin.py."""
    if count_super_admins(session) > 0:
        raise ServiceError("An administrator already exists. Initial setup is disabled.")
    return _create_user(session, full_name, email, password, "SUPER_ADMIN")


def _create_user(session: Session, full_name: str, email: str, password: str, role: str) -> User:
    name = require_text(full_name, "Full name", 150)
    email = validate_email(email)
    if role not in ROLES:
        raise ValidationError("Select a valid role.")
    errors = password_policy_errors(password)
    if errors:
        raise ValidationError(" ".join(errors))
    user = User(full_name=name, email=email, password_hash=hash_password(password), role=role)
    with integrity_guard(session, "A user with this email already exists."):
        session.add(user)
    return user


def create_user(session: Session, actor: User, full_name: str, email: str, password: str, role: str) -> User:
    require(actor, Permission.MANAGE_USERS)
    return _create_user(session, full_name, email, password, role)


def list_users(session: Session, actor: User) -> list[User]:
    require(actor, Permission.MANAGE_USERS)
    return list(session.scalars(select(User).order_by(User.full_name)))


def set_user_status(session: Session, actor: User, user_id: int, active: bool) -> User:
    require(actor, Permission.MANAGE_USERS)
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User was not found.")
    if not active:
        if user.id == actor.id:
            raise ValidationError("You cannot deactivate your own account.")
        if user.role == "SUPER_ADMIN" and count_active_super_admins(session) <= 1:
            raise ValidationError("The last active super admin cannot be deactivated.")
    user.status = "ACTIVE" if active else "INACTIVE"
    if not active:
        for s in session.scalars(select(UserSession).where(UserSession.user_id == user.id)):
            s.revoked = True
    session.flush()
    return user


def set_user_role(session: Session, actor: User, user_id: int, role: str) -> User:
    require(actor, Permission.MANAGE_USERS)
    if role not in ROLES:
        raise ValidationError("Select a valid role.")
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User was not found.")
    if user.role == "SUPER_ADMIN" and role != "SUPER_ADMIN" and count_active_super_admins(session) <= 1:
        raise ValidationError("The last active super admin cannot be demoted.")
    user.role = role
    session.flush()
    return user


def count_active_super_admins(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == "SUPER_ADMIN", User.status == "ACTIVE")) or 0


def change_password(session: Session, actor: User, current_password: str, new_password: str) -> None:
    if actor is None or actor.status != "ACTIVE":
        raise AuthenticationError("You must be signed in.")
    user = session.get(User, actor.id)
    if not verify_password(current_password or "", user.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    errors = password_policy_errors(new_password)
    if errors:
        raise ValidationError(" ".join(errors))
    if verify_password(new_password, user.password_hash):
        raise ValidationError("The new password must differ from the current password.")
    user.password_hash = hash_password(new_password)
    session.flush()
