"""Protocol registry. Plug new LLM protocols (harmony / openai / mock / etc.)
via @register_protocol.

Routing order at resolve time:
1. Explicit override (`endpoint.protocol` / `--agent ...,protocol=harmony`)
2. First registered protocol whose `model_pattern` matches `endpoint.name`
3. The protocol marked `default=True` (built-in: openai)
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

from agent_cap.agents.types import ModelEndpoint

_T = TypeVar("_T")

_PROTOCOLS: Dict[str, Type] = {}
_PATTERNS: List[Tuple[re.Pattern, str]] = []
_DEFAULT: Optional[str] = None


def register_protocol(
    name: str,
    *,
    model_pattern: Optional[str] = None,
    default: bool = False,
) -> Callable[[Type[_T]], Type[_T]]:
    key = str(name).strip()
    if not key:
        raise ValueError("protocol name must be non-empty")

    def deco(cls: Type[_T]) -> Type[_T]:
        _PROTOCOLS[key] = cls
        if model_pattern:
            _PATTERNS.append((re.compile(model_pattern), key))
        if default:
            global _DEFAULT
            _DEFAULT = key
        return cls

    return deco


def resolve_protocol_name(endpoint: ModelEndpoint) -> str:
    """Pick the protocol name for an endpoint without instantiating it."""
    explicit = getattr(endpoint, "protocol", "") or ""
    if explicit:
        explicit = str(explicit).strip()
        if explicit not in _PROTOCOLS:
            raise KeyError(
                f"Unknown protocol '{explicit}'. Registered: {sorted(_PROTOCOLS)}"
            )
        return explicit

    for pat, proto in _PATTERNS:
        if pat.search(endpoint.name or ""):
            return proto

    if _DEFAULT is None:
        raise RuntimeError(
            "No default protocol registered. "
            "Did you import agent_cap.agents.llm at startup?"
        )
    return _DEFAULT


def get_protocol_cls(name: str) -> Type:
    if name not in _PROTOCOLS:
        raise KeyError(f"Unknown protocol '{name}'. Registered: {sorted(_PROTOCOLS)}")
    return _PROTOCOLS[name]


def list_protocols() -> List[str]:
    return sorted(_PROTOCOLS.keys())


def make_client(endpoint: ModelEndpoint, **kwargs: Any) -> Any:
    """Build the LLM client for an endpoint, auto-routing by name."""
    proto = resolve_protocol_name(endpoint)
    cls = get_protocol_cls(proto)
    return cls(**kwargs)


__all__ = [
    "register_protocol",
    "resolve_protocol_name",
    "get_protocol_cls",
    "list_protocols",
    "make_client",
]
