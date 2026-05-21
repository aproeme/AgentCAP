"""Tool provider abstraction and a minimal local tool registry.

A `ToolProvider` exposes:
- list_tools() -> OpenAI-style tool schemas
- call(name, args) -> string result

Strategies pass these to the LLM unchanged. The CLI ships with a tiny in-process
provider that can be extended by registering Python callables. For real tool
backends (MCP, SWE-bench, etc.) wrap them with a thin adapter.
"""

from __future__ import annotations

import inspect
import json
import math
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol


class ToolProvider(Protocol):
    async def list_tools(self) -> List[Dict[str, Any]]: ...
    async def call(self, name: str, arguments: Dict[str, Any]) -> str: ...


ToolFn = Callable[..., Any]


class LocalToolRegistry:
    """In-process tool provider. Register sync or async callables."""

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._fns: Dict[str, ToolFn] = {}

    def register(
        self,
        name: str,
        fn: ToolFn,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not name:
            raise ValueError("tool name must be non-empty")
        self._tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description or (fn.__doc__ or "").strip(),
                "parameters": parameters or {"type": "object", "properties": {}},
            },
        }
        self._fns[name] = fn

    def tool(self, name: Optional[str] = None, description: str = "",
             parameters: Optional[Dict[str, Any]] = None) -> Callable[[ToolFn], ToolFn]:
        def deco(fn: ToolFn) -> ToolFn:
            self.register(name or fn.__name__, fn, description=description, parameters=parameters)
            return fn
        return deco

    async def list_tools(self) -> List[Dict[str, Any]]:
        return list(self._tools.values())

    async def call(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self._fns:
            return f"ERROR: unknown tool '{name}'"
        fn = self._fns[name]
        try:
            result: Any
            if inspect.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                result = fn(**arguments)
        except Exception as exc:
            return f"ERROR: {exc}"
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False)
        return str(result)


def build_demo_tools() -> LocalToolRegistry:
    """Tiny demo toolkit: calculator + echo. Used by --mock and as an example."""
    reg = LocalToolRegistry()

    @reg.tool(
        name="calc",
        description="Evaluate a simple arithmetic expression and return the number.",
        parameters={
            "type": "object",
            "properties": {"expr": {"type": "string"}},
            "required": ["expr"],
        },
    )
    def calc(expr: str) -> str:
        allowed = {k: getattr(math, k) for k in ("sqrt", "log", "exp", "sin", "cos", "pi", "e")}
        return str(eval(expr, {"__builtins__": {}}, allowed))  # noqa: S307 - sandboxed

    @reg.tool(
        name="echo",
        description="Return the message verbatim.",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    def echo(message: str) -> str:
        return message

    return reg


__all__ = ["ToolProvider", "LocalToolRegistry", "build_demo_tools"]
