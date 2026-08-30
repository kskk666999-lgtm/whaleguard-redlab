"""WhaleGuard fail-closed authorization and network policy engine."""

from .client import ScopedAsyncClient
from .models import (
    ApprovalState,
    AuthorizationScope,
    PolicyDecision,
    RequestContext,
    RiskLevel,
)
from .scope_guard import ScopeGuard

__all__ = [
    "ApprovalState",
    "AuthorizationScope",
    "PolicyDecision",
    "RequestContext",
    "RiskLevel",
    "ScopeGuard",
    "ScopedAsyncClient",
]

__version__ = "0.1.1"
