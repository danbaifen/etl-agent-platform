from __future__ import annotations

from dataclasses import dataclass

ROLE_MAKER = "MAKER"
ROLE_CHECKER_DATA = "CHECKER_DATA"
ROLE_CHECKER_SECURITY = "CHECKER_SECURITY"
ROLE_OPERATOR = "OPERATOR"
ROLE_AUDITOR = "AUDITOR"
ROLE_PROJECT_ADMIN = "PROJECT_ADMIN"


@dataclass(frozen=True)
class RoleDef:
    code: str
    name: str
    is_business_approval_role: bool
    capabilities: frozenset[str]


_BASE_READ = frozenset({"iam:project:read", "iam:member:read", "auth:session:write"})

ROLES: dict[str, RoleDef] = {
    ROLE_PROJECT_ADMIN: RoleDef(
        ROLE_PROJECT_ADMIN,
        "项目管理员",
        False,
        frozenset(
            {
                "iam:project:read",
                "iam:project:write",
                "iam:member:read",
                "iam:member:write",
                "iam:role:assign",
                "auth:session:write",
            }
        ),
    ),
    ROLE_MAKER: RoleDef(ROLE_MAKER, "需求提出者", False, _BASE_READ),
    ROLE_CHECKER_DATA: RoleDef(ROLE_CHECKER_DATA, "审批人·业务维度", True, _BASE_READ),
    ROLE_CHECKER_SECURITY: RoleDef(ROLE_CHECKER_SECURITY, "审批人·安全维度", True, _BASE_READ),
    ROLE_OPERATOR: RoleDef(ROLE_OPERATOR, "操作员", False, _BASE_READ),
    ROLE_AUDITOR: RoleDef(ROLE_AUDITOR, "审计", False, _BASE_READ),
}

# 业务模块能力在此追加，按「角色 → 能力」汇总后下发给前端。
# 只读能力（*:read）下放给所有业务角色，写能力按职责严格限定。
_READ_ALL = frozenset(
    {
        "asset:connection:read",
        "meta:probe:read",
        "studio:session:read",
        "pipe:version:read",
        "harness:preparation:read",
        "exec:run:read",
        "bench:suite:read",
        "evidence:ledger:read",
    }
)

EXTRA_CAPABILITIES: dict[str, frozenset[str]] = {
    ROLE_MAKER: _READ_ALL
    | frozenset(
        {
            "asset:connection:write",
            "asset:connection:test",
            "meta:probe:run",
            "studio:session:write",
            "pipe:version:freeze",
            "harness:prepare",
        }
    ),
    ROLE_CHECKER_DATA: _READ_ALL | frozenset({"asset:connection:test"}),
    ROLE_CHECKER_SECURITY: _READ_ALL
    | frozenset(
        {
            "asset:connection:test",
            "asset:secret:read",
            "bench:suite:write",
            "bench:run:trigger",
        }
    ),
    ROLE_OPERATOR: _READ_ALL
    | frozenset(
        {
            "asset:connection:test",
            "asset:secret:rotate",
            "harness:commit",
            "exec:run:control",
        }
    ),
    ROLE_AUDITOR: _READ_ALL,
    ROLE_PROJECT_ADMIN: _READ_ALL,
}


def capabilities_for(role_codes: list[str] | tuple[str, ...]) -> frozenset[str]:
    caps: set[str] = set()
    for code in role_codes:
        role = ROLES.get(code)
        if role:
            caps |= role.capabilities
        caps |= EXTRA_CAPABILITIES.get(code, frozenset())
    return frozenset(caps)


def approval_slots_for(role_codes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    slots: list[str] = []
    if ROLE_CHECKER_DATA in role_codes:
        slots.append("DATA")
    if ROLE_CHECKER_SECURITY in role_codes:
        slots.append("SECURITY")
    return tuple(slots)


def is_known_role(code: str) -> bool:
    return code in ROLES


# 强制职责分离：以下组合不允许出现在同一成员身上（项目要求 2.8.2）
# 1) 申请人（MAKER）不得兼任任何审批槽，否则可自批；
# 2) 两个审批槽（业务 / 安全）不得由同一人兼任，否则四眼原则失效。
_APPROVAL_ROLES = frozenset({ROLE_CHECKER_DATA, ROLE_CHECKER_SECURITY})

_FORBIDDEN_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({ROLE_MAKER, ROLE_CHECKER_DATA}),
    frozenset({ROLE_MAKER, ROLE_CHECKER_SECURITY}),
    frozenset({ROLE_CHECKER_DATA, ROLE_CHECKER_SECURITY}),
)


def duty_conflict(existing: list[str] | tuple[str, ...], incoming: str) -> tuple[str, str] | None:
    """返回 (已持有角色, 新角色) 冲突对；无冲突返回 None。"""
    held = set(existing)
    for pair in _FORBIDDEN_PAIRS:
        if incoming in pair and (pair - {incoming}) & held:
            other = next(iter((pair - {incoming}) & held))
            return other, incoming
    return None


def duty_conflict_reason(code_a: str, code_b: str) -> str:
    if code_a == ROLE_MAKER or code_b == ROLE_MAKER:
        return "需求提出者（MAKER）不得同时担任审批人，否则无法满足申请人不得自批的要求"
    if {code_a, code_b} == set(_APPROVAL_ROLES):
        return "业务审批人与安全审批人必须由不同人员担任，否则四眼原则失效"
    return "角色组合违反职责分离要求"
