from datetime import timedelta

import pytest
from sqlalchemy import select

from auth import service
from auth.permissions import Permission, PermissionDenied, has_permission, require
from auth.security import hash_password, password_policy_errors, verify_password
from database.models import User, UserSession
from services.common import ServiceError, utcnow


def test_password_hashing_argon2_never_plaintext(session, super_admin):
    row = session.scalar(select(User).where(User.id == super_admin.id))
    assert row.password_hash.startswith("$argon2") and "StrongPass123" not in row.password_hash
    assert verify_password("StrongPass123", row.password_hash)
    assert not verify_password("wrong", row.password_hash)
    assert hash_password("same") != hash_password("same")      # salted


def test_repr_does_not_leak_hash(super_admin):
    assert super_admin.password_hash not in repr(super_admin)


def test_successful_login_creates_session_and_validates(session, super_admin):
    user, token = service.authenticate(session, "SUPER@example.test", "StrongPass123")
    assert user.last_login is not None
    assert service.validate_session(session, token).id == user.id
    stored = session.scalar(select(UserSession))
    assert stored.token_hash != token                          # only the hash is stored


def test_invalid_credentials_are_generic(session, super_admin):
    for email, pw in (("super@example.test", "bad"), ("nobody@example.test", "StrongPass123")):
        with pytest.raises(service.AuthenticationError) as e:
            service.authenticate(session, email, pw)
        assert str(e.value) == service.GENERIC_LOGIN_ERROR


def test_lockout_after_repeated_failures(session, super_admin):
    for _ in range(service.MAX_FAILED_ATTEMPTS):
        with pytest.raises(service.AuthenticationError):
            service.authenticate(session, "super@example.test", "bad")
    with pytest.raises(service.AuthenticationError, match="Too many"):
        service.authenticate(session, "super@example.test", "StrongPass123")     # even the right password is refused
    session.get(User, super_admin.id).locked_until = utcnow() - timedelta(minutes=1)
    session.commit()
    assert service.authenticate(session, "super@example.test", "StrongPass123")


def test_inactive_account_cannot_sign_in(session, super_admin, admin):
    service.set_user_status(session, super_admin, admin.id, False)
    with pytest.raises(service.AuthenticationError, match="inactive"):
        service.authenticate(session, "admin@example.test", "StrongPass123")


def test_deactivation_revokes_existing_session(session, super_admin, admin):
    _, token = service.authenticate(session, "admin@example.test", "StrongPass123")
    service.set_user_status(session, super_admin, admin.id, False)
    assert service.validate_session(session, token) is None


def test_logout_and_expiry(session, super_admin):
    _, token = service.authenticate(session, "super@example.test", "StrongPass123")
    service.logout(session, token)
    assert service.validate_session(session, token) is None
    _, t2 = service.authenticate(session, "super@example.test", "StrongPass123")
    row = session.scalar(select(UserSession).where(UserSession.revoked.is_(False)))
    row.expires_at = utcnow() - timedelta(seconds=1); session.commit()
    assert service.validate_session(session, t2) is None
    assert service.validate_session(session, "garbage") is None and service.validate_session(session, None) is None


def test_first_admin_only_once(session):
    u = service.create_first_admin(session, "First Admin", "first@example.test", "StrongPass123")
    assert u.role == "SUPER_ADMIN"
    with pytest.raises(ServiceError, match="already exists"):
        service.create_first_admin(session, "Second", "second@example.test", "StrongPass123")


def test_weak_passwords_rejected(session):
    assert password_policy_errors("short")
    with pytest.raises(ServiceError):
        service.create_first_admin(session, "A", "a@example.test", "alllowercase1")


def test_change_password(session, admin):
    with pytest.raises(service.AuthenticationError):
        service.change_password(session, admin, "wrong", "NewStrongPass1")
    service.change_password(session, admin, "StrongPass123", "NewStrongPass1")
    assert service.authenticate(session, "admin@example.test", "NewStrongPass1")


def test_permission_matrix(super_admin, admin, viewer):
    for p in Permission:
        assert has_permission(super_admin, p)
    assert has_permission(admin, Permission.GENERATE) and has_permission(admin, Permission.MANAGE_RECORDS)
    for p in (Permission.MANAGE_USERS, Permission.APPROVE, Permission.PUBLISH, Permission.MANAGE_DEPARTMENTS, Permission.MANAGE_SETTINGS):
        assert not has_permission(admin, p)
    assert has_permission(viewer, Permission.VIEW_PUBLISHED) and not has_permission(viewer, Permission.VIEW_ALL_TIMETABLES)
    for p in (Permission.GENERATE, Permission.MANAGE_RECORDS, Permission.VIEW_RECORDS):
        assert not has_permission(viewer, p)
    with pytest.raises(PermissionDenied):
        require(None, Permission.VIEW_PUBLISHED)


def test_dataset_permissions(super_admin, admin, viewer):
    assert has_permission(admin, Permission.IMPORT_DATASETS) and not has_permission(admin, Permission.REMOVE_DATASETS)
    assert has_permission(super_admin, Permission.REMOVE_DATASETS)
    assert not has_permission(viewer, Permission.IMPORT_DATASETS) and not has_permission(viewer, Permission.REMOVE_DATASETS)


def test_inactive_user_loses_all_permissions(super_admin):
    super_admin.status = "INACTIVE"
    assert not has_permission(super_admin, Permission.VIEW_PUBLISHED)


def test_user_management_protected_and_guards(session, super_admin, admin):
    with pytest.raises(PermissionDenied):
        service.create_user(session, admin, "X", "x@example.test", "StrongPass123", "ADMIN")
    with pytest.raises(PermissionDenied):
        service.list_users(session, admin)
    with pytest.raises(ServiceError, match="own account"):
        service.set_user_status(session, super_admin, super_admin.id, False)
    with pytest.raises(ServiceError, match="last"):
        service.set_user_role(session, super_admin, super_admin.id, "ADMIN")
    with pytest.raises(ServiceError, match="already exists"):
        service.create_user(session, super_admin, "Dup", "admin@example.test", "StrongPass123", "ADMIN")
