"""User management schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field, StringConstraints

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_core.enums import MembershipStatus, Role, UserStatus

Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]


class MembershipOut(Schema):
    id: uuid.UUID
    role: Role
    status: MembershipStatus
    all_brands: bool = Field(alias="allBrands")
    granted_at: datetime = Field(alias="grantedAt")


class UserOut(Schema):
    id: uuid.UUID
    email: str
    display_name: str = Field(alias="displayName")
    status: UserStatus
    mfa_enrolled: bool = Field(alias="mfaEnrolled")
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")
    is_platform_admin: bool = Field(default=False, alias="isPlatformAdmin")
    memberships: list[MembershipOut] = Field(default_factory=list)
    audit: AuditStamp


class UserInvite(Schema):
    email: EmailStr
    display_name: Name = Field(alias="displayName")
    role: Role
    all_brands: bool = Field(default=True, alias="allBrands")


class UserRoleUpdate(Schema):
    role: Role
    all_brands: bool = Field(default=True, alias="allBrands")
    version: int


class DeactivateUserRequest(Schema):
    reason: str = Field(min_length=1, max_length=500)


__all__ = [
    "DeactivateUserRequest",
    "MembershipOut",
    "UserInvite",
    "UserOut",
    "UserRoleUpdate",
]
