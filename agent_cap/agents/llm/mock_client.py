from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from agent_cap.agents.llm.base import LLMReply
from agent_cap.agents.llm.registry import register_protocol
from agent_cap.agents.types import ModelEndpoint, Usage


@register_protocol("mock", model_pattern=r"(?i)^mock(-|$)")
class MockLLMClient:
    """Deterministic offline LLM. Activates explicitly or when model name
    starts with `mock-` / equals `mock`.

    Routing:
    - role looks like planner -> emits a 2-step plan
    - any other role with tools available -> calls the first tool
    - otherwise -> emits a final ANSWER line
    """

    def __init__(self, **_: Any) -> None:
        pass

    async def chat(
        self,
        endpoint: ModelEndpoint,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMReply:
        t0 = time.perf_counter()
        user_text = _last_user_text(messages)
        system_text = _system_text(messages)
        is_planner = (
            "planner" in (system_text + endpoint.name).lower()
            or "plan" in endpoint.name.lower()
        )
        prior_tool_msgs = [m for m in messages if m.get("role") == "tool"]

        if is_planner:
            content = (
                "Plan:\n"
                f"1. Inspect the request: '{user_text[:80]}'.\n"
                "2. If a tool is available call it once with the simplest input, "
                "then write a final ANSWER line."
            )
            assistant: Dict[str, Any] = {"role": "assistant", "content": content}
        elif tools and not prior_tool_msgs:
            tool_name = tools[0]["function"]["name"]
            args = _guess_args(tool_name, user_text)
            assistant = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(args)},
                    }
                ],
            }
        else:
            tail = ""
            if prior_tool_msgs:
                tail = f" Tool said: {prior_tool_msgs[-1].get('content', '')}".strip()
            assistant = {
                "role": "assistant",
                "content": f"ANSWER: mock reply for '{user_text[:60]}'.{tail}",
            }

        n_in = sum(len(str(m.get("content", ""))) for m in messages) // 4
        n_out = len(str(assistant.get("content", ""))) // 4 + 1
        return LLMReply(
            assistant=assistant,
            usage=Usage(input_tokens=n_in, output_tokens=n_out, cached_tokens=0, requests=1),
            latency_s=time.perf_counter() - t0,
            raw={
                "choices": [{"message": assistant}],
                "usage": {"prompt_tokens": n_in, "completion_tokens": n_out},
            },
        )


def _last_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            return c if isinstance(c, str) else json.dumps(c)
    return ""


def _system_text(messages: List[Dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")


def _guess_args(tool_name: str, user_text: str) -> Dict[str, Any]:
    if tool_name == "calc":
        m = re.search(r"[-+]?\d+(?:\.\d+)?(?:\s*[-+*/]\s*[-+]?\d+(?:\.\d+)?)+", user_text)
        return {"expr": m.group(0) if m else "1+1"}
    if tool_name == "echo":
        return {"message": user_text[:120] or "hello"}
    if tool_name in ("python", "math_python", "math-python"):
        return {"code": "print(1+1)"}
    return {}


__all__ = ["MockLLMClient"]
