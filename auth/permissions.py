"""Central role/permission definitions. Services call require() on every protected operation."""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Permission(str, Enum):
    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_DEPARTMENTS = "MANAGE_DEPARTMENTS"
    MANAGE_RECORDS = "MANAGE_RECORDS"      # lecturers, courses, classrooms, groups, assignments, availability
    VIEW_RECORDS = "VIEW_RECORDS"
    CONFIGURE_ALGORITHM = "CONFIGURE_ALGORITHM"
    GENERATE = "GENERATE"
    APPROVE = "APPROVE"
    PUBLISH = "PUBLISH"
    VIEW_ALL_TIMETABLES = "VIEW_ALL_TIMETABLES"
    VIEW_PUBLISHED = "VIEW_PUBLISHED"
    EXPORT = "EXPORT"
    VIEW_HISTORY = "VIEW_HISTORY"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"
    IMPORT_DATASETS = "IMPORT_DATASETS"     # import, view, validate and generate synthetic test layers from datasets
    REMOVE_DATASETS = "REMOVE_DATASETS"     # remove a test dataset (super admin only)


P = Permission
ROLE_PERMISSIONS = {
    "SUPER_ADMIN": frozenset(Permission),
    "ADMIN": frozenset({P.MANAGE_RECORDS, P.VIEW_RECORDS, P.GENERATE, P.VIEW_ALL_TIMETABLES, P.VIEW_PUBLISHED,
                        P.EXPORT, P.VIEW_HISTORY, P.IMPORT_DATASETS}),
    "VIEWER": frozenset({P.VIEW_PUBLISHED, P.EXPORT}),
}
ROLE_LABELS = {"SUPER_ADMIN": "Super admin", "ADMIN": "Admin", "VIEWER": "Viewer"}


class PermissionDenied(Exception):
    """Raised when the acting user lacks a permission (or is not signed in / active)."""


def has_permission(user: Optional[object], permission: Permission) -> bool:
    if user is None or getattr(user, "status", None) != "ACTIVE":
        return False
    return permission in ROLE_PERMISSIONS.get(getattr(user, "role", ""), frozenset())


def require(user: Optional[object], permission: Permission) -> None:
    if not has_permission(user, permission):
        raise PermissionDenied("You do not have permission to perform this action.")
