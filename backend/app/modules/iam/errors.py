from __future__ import annotations

from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized

AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
AUTH_USER_DISABLED = "AUTH_USER_DISABLED"
AUTH_ACCOUNT_LOCKED = "AUTH_ACCOUNT_LOCKED"
AUTH_PROVIDER_DISABLED = "AUTH_PROVIDER_DISABLED"
AUTH_UNAUTHENTICATED = "AUTH_UNAUTHENTICATED"
AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
AUTH_SESSION_REVOKED = "AUTH_SESSION_REVOKED"

IAM_INVALID_CODE_FORMAT = "IAM_INVALID_CODE_FORMAT"
IAM_PROJECT_CODE_CONFLICT = "IAM_PROJECT_CODE_CONFLICT"
IAM_PROJECT_NOT_FOUND = "IAM_PROJECT_NOT_FOUND"
IAM_PROJECT_SUSPENDED = "IAM_PROJECT_SUSPENDED"
IAM_NOT_MEMBER = "IAM_NOT_MEMBER"
IAM_USER_NOT_FOUND = "IAM_USER_NOT_FOUND"
IAM_MEMBER_EXISTS = "IAM_MEMBER_EXISTS"
IAM_MEMBER_NOT_FOUND = "IAM_MEMBER_NOT_FOUND"
IAM_ROLE_UNKNOWN = "IAM_ROLE_UNKNOWN"
IAM_ROLE_ALREADY_ASSIGNED = "IAM_ROLE_ALREADY_ASSIGNED"
IAM_ASSIGNMENT_NOT_FOUND = "IAM_ASSIGNMENT_NOT_FOUND"
IAM_SCOPE_MISMATCH = "IAM_SCOPE_MISMATCH"
IAM_ROLE_DUTY_CONFLICT = "IAM_ROLE_DUTY_CONFLICT"
IAM_MEMBER_INACTIVE = "IAM_MEMBER_INACTIVE"


def invalid_credentials() -> Unauthorized:
    return Unauthorized(AUTH_INVALID_CREDENTIALS, "账号或密码不正确")


def user_disabled() -> Forbidden:
    return Forbidden(AUTH_USER_DISABLED, "账号已停用，请联系项目管理员")


def account_locked(until: str) -> AppError:
    return AppError(AUTH_ACCOUNT_LOCKED, "失败次数过多，请稍后重试", 423, {"locked_until": until})


def not_member() -> Forbidden:
    return Forbidden(IAM_NOT_MEMBER, "不是该项目成员")


def member_not_found() -> NotFound:
    return NotFound(IAM_MEMBER_NOT_FOUND, "成员不属于该项目")


def role_unknown(code: str) -> AppError:
    return AppError(IAM_ROLE_UNKNOWN, f"未知角色：{code}", 400)


def already_assigned() -> Conflict:
    return Conflict(IAM_ROLE_ALREADY_ASSIGNED, "该成员已持有此角色")


def duty_conflict(held: str, incoming: str, reason: str) -> Conflict:
    return Conflict(
        IAM_ROLE_DUTY_CONFLICT,
        f"角色冲突：{held} 与 {incoming}。{reason}",
        {"held_role": held, "incoming_role": incoming, "rule": "SEPARATION_OF_DUTY"},
    )


def member_inactive() -> Conflict:
    return Conflict(IAM_MEMBER_INACTIVE, "成员已移除，请先恢复成员状态再分配角色")
