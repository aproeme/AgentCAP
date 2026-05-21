"""Pluggable registries for strategies and agent factories.

Custom code can extend the system with:

    from agent_cap.agents import register_strategy, Strategy

    @register_strategy("my-strategy")
    class MyStrategy(Strategy):
        required_roles = ("planner", "executor", "critic")
        async def run(self, task, agents, tools): ...

The CLI auto-discovers strategies registered at import time. To load a user's
module containing custom strategies, pass `--load-module my.module.path` to the
CLI (it just calls importlib.import_module).
"""

from __future__ import annotations

import importlib
from typing import Callable, Dict, List, Type, TypeVar

_T = TypeVar("_T")

_STRATEGIES: Dict[str, "Type"] = {}
_AGENT_FACTORIES: Dict[str, Callable[..., object]] = {}


def register_strategy(name: str) -> Callable[[Type[_T]], Type[_T]]:
    key = str(name).strip()
    if not key:
        raise ValueError("strategy name must be non-empty")

    def deco(cls: Type[_T]) -> Type[_T]:
        if key in _STRATEGIES:
            raise ValueError(f"strategy '{key}' already registered")
        _STRATEGIES[key] = cls
        return cls

    return deco


def get_strategy(name: str) -> "Type":
    if name not in _STRATEGIES:
        raise KeyError(
            f"Unknown strategy '{name}'. Available: {sorted(_STRATEGIES.keys())}"
        )
    return _STRATEGIES[name]


def list_strategies() -> List[str]:
    return sorted(_STRATEGIES.keys())


def register_agent_factory(name: str, factory: Callable[..., object]) -> None:
    key = str(name).strip()
    if not key:
        raise ValueError("factory name must be non-empty")
    _AGENT_FACTORIES[key] = factory


def get_agent_factory(name: str) -> Callable[..., object]:
    if name not in _AGENT_FACTORIES:
        raise KeyError(
            f"Unknown agent factory '{name}'. Available: {sorted(_AGENT_FACTORIES.keys())}"
        )
    return _AGENT_FACTORIES[name]


def list_agent_factories() -> List[str]:
    return sorted(_AGENT_FACTORIES.keys())


def load_modules(module_paths: List[str]) -> None:
    """Import each path so its `@register_strategy` decorators run."""
    for path in module_paths:
        path = path.strip()
        if not path:
            continue
        importlib.import_module(path)


__all__ = [
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "register_agent_factory",
    "get_agent_factory",
    "list_agent_factories",
    "load_modules",
]
