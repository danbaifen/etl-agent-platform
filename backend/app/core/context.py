from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """跨模块共享的只读上下文。下游不得修改后继续传递。

    tenant_id / project_id 只来自会话，绝不接受请求体传入。
    """

    trace_id: str
    user_id: uuid.UUID
    display_name: str
    tenant_id: uuid.UUID
    project_id: uuid.UUID | None = None
    roles: tuple[str, ...] = ()
    approval_slots: tuple[str, ...] = ()
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def require(self, capability: str) -> None:
        from app.core.errors import Forbidden

        if not self.has(capability):
            raise Forbidden("AUTH_FORBIDDEN", f"缺少权限：{capability}")
