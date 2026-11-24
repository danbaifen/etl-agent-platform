from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class LoginRequest(BaseModel):
    provider: str = Field(default="LOCAL", pattern="^(LOCAL|OIDC)$")
    external_subject: str = Field(min_length=1, max_length=256)
    credential: str = Field(min_length=8, max_length=128)


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    status: str


class TenantBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class ProjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: str


class LoginResponse(BaseModel):
    session_token: str
    expires_at: datetime
    user: UserBrief
    projects: list[ProjectBrief]


class SessionResponse(BaseModel):
    user: UserBrief
    tenant: TenantBrief
    project: ProjectBrief | None
    roles: list[str]
    approval_slots: list[str]
    capabilities: list[str]


class SwitchProjectRequest(BaseModel):
    project_id: uuid.UUID


class CreateProjectRequest(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=128)

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not CODE_PATTERN.match(v):
            raise ValueError("code 只允许小写字母、数字与连字符，且首尾为字母或数字")
        return v


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern="^(ACTIVE|SUSPENDED|ARCHIVED)$")


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class RoleBrief(BaseModel):
    code: str
    name: str
    is_business_approval_role: bool


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email_masked: str | None
    roles: list[RoleBrief]
    status: str
    last_login_at: datetime | None


class InviteMemberRequest(BaseModel):
    external_subject: str = Field(min_length=1, max_length=256)
    role_codes: list[str] = Field(min_length=1)


class UpdateMemberRequest(BaseModel):
    status: str = Field(pattern="^(ACTIVE|REMOVED)$")


class AssignRoleRequest(BaseModel):
    role_code: str
    valid_from: datetime | None = None
    reason: str = Field(min_length=3, max_length=256)


class PageMeta(BaseModel):
    next_cursor: str | None = None


class MemberPage(BaseModel):
    items: list[MemberResponse]
    next_cursor: str | None = None


class ProjectPage(BaseModel):
    items: list[ProjectResponse]
    next_cursor: str | None = None
