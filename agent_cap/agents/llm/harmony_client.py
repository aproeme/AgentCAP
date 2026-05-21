"""OpenAI Harmony protocol client for gpt-oss family models.

Models like `gpt-oss-120b` / `gpt-oss-20b` use the Harmony chat template, which
encodes/decodes conversations at the token level via `openai_harmony`. They
expose only the `/v1/completions` endpoint (NOT `/v1/chat/completions`).

This client converts OpenAI-style messages+tools to Harmony Messages, renders
them to token ids, calls the vLLM/sglang `/v1/completions` endpoint with
`prompt=<token_ids>`, then decodes the response back into OpenAI-style
`tool_calls` so the rest of the framework can stay protocol-agnostic.

Auto-routes on model names matching `(?i)gpt-?oss`. Override with
`--agent ...,protocol=harmony` or `,protocol=openai`.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp

from agent_cap.agents.llm.base import LLMReply
from agent_cap.agents.llm.registry import register_protocol
from agent_cap.agents.types import ModelEndpoint, Usage


@register_protocol("harmony", model_pattern=r"(?i)gpt-?oss")
class HarmonyClient:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None, **_: Any) -> None:
        self._session = session
        self._encoding = None
        self._stop_token_ids: List[int] = []

    def _ensure_encoding(self) -> Any:
        if self._encoding is not None:
            return self._encoding
        try:
            from openai_harmony import HarmonyEncodingName, load_harmony_encoding
        except ImportError as exc:
            raise RuntimeError(
                "harmony protocol requires `openai_harmony`. "
                "Install it or use `--agent ...,protocol=openai`."
            ) from exc
        self._encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
        try:
            self._stop_token_ids = list(
                self._encoding.stop_tokens_for_assistant_actions()
            )
        except Exception:
            self._stop_token_ids = [200002, 200012]
        return self._encoding

    async def chat(
        self,
        endpoint: ModelEndpoint,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMReply:
        if self._session is None:
            raise RuntimeError(
                "HarmonyClient requires an aiohttp.ClientSession. "
                "Construct it inside `async with aiohttp.ClientSession() as session:`."
            )

        from openai_harmony import (
            Author,
            Conversation,
            Message,
            ReasoningEffort,
            Role,
            SystemContent,
            ToolNamespaceConfig,
        )

        encoding = self._ensure_encoding()

        sys_content = SystemContent.new().with_reasoning_effort(
            reasoning_effort=ReasoningEffort.HIGH
        )
        if tools:
            tool_cfg = _harmony_tool_config(tools, ToolNamespaceConfig)
            if tool_cfg is not None:
                sys_content = sys_content.with_tools(tool_cfg)

        harmony_messages: List[Any] = []
        system_used = False
        for m in messages:
            role = str(m.get("role", "")).lower()
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content) if content is not None else ""

            if role == "system":
                merged = sys_content.with_model_identity(content) if content else sys_content
                harmony_messages.append(Message.from_role_and_content(Role.SYSTEM, merged))
                system_used = True
            elif role == "user":
                harmony_messages.append(Message.from_role_and_content(Role.USER, content))
            elif role == "assistant":
                harmony_messages.append(Message.from_role_and_content(Role.ASSISTANT, content))
            elif role == "tool":
                tool_name = str(m.get("name") or m.get("tool_call_id") or "python")
                msg = Message.from_role_and_content(Role.TOOL, content)
                msg.author = Author(role=Role.TOOL, name=tool_name)
                harmony_messages.append(msg)

        if not system_used:
            harmony_messages.insert(
                0, Message.from_role_and_content(Role.SYSTEM, sys_content)
            )

        conversation = Conversation.from_messages(harmony_messages)
        prompt_ids = encoding.render_conversation_for_completion(
            conversation, Role.ASSISTANT
        )

        completions_url = endpoint.base_url.rstrip("/") + "/completions"
        payload = {
            "model": endpoint.name,
            "prompt": prompt_ids,
            "max_tokens": max(1, int(endpoint.max_tokens) - len(prompt_ids)),
            "temperature": float(endpoint.temperature),
            "stop_token_ids": list(self._stop_token_ids),
        }
        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"

        t0 = time.perf_counter()
        async with self._session.post(
            completions_url, json=payload, headers=headers
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(
                    f"Harmony completions failed ({resp.status}): {text[:500]}"
                )
            raw = json.loads(text)
        elapsed = time.perf_counter() - t0

        choices = raw.get("choices") or []
        token_ids = (
            (choices[0].get("token_ids") if choices else None)
            or (choices[0].get("logprobs", {}).get("tokens") if choices else None)
            or []
        )
        completion_text = (choices[0].get("text", "") if choices else "") or ""

        assistant = _decode_harmony_response(
            encoding=encoding,
            token_ids=token_ids,
            fallback_text=completion_text,
            Role=Role,
        )

        usage_raw = raw.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens", len(prompt_ids)) or len(prompt_ids)),
            output_tokens=int(usage_raw.get("completion_tokens", len(token_ids) if token_ids else 0) or 0),
            cached_tokens=int(
                (usage_raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
            ),
            requests=1,
        )
        return LLMReply(assistant=assistant, usage=usage, latency_s=elapsed, raw=raw)


def _harmony_tool_config(tools: List[Dict[str, Any]], ToolNamespaceConfig: Any) -> Any:
    if not tools:
        return None
    first = tools[0].get("function") or {}
    name = first.get("name") or "python"
    desc = first.get("description") or (
        "Use this tool to execute the necessary action. "
        "Always finalize with an ANSWER line."
    )
    return ToolNamespaceConfig(name=name, description=desc, tools=[])


def _decode_harmony_response(
    *,
    encoding: Any,
    token_ids: List[int],
    fallback_text: str,
    Role: Any,
) -> Dict[str, Any]:
    if not token_ids:
        return {"role": "assistant", "content": fallback_text}
    try:
        parsed = encoding.parse_messages_from_completion_tokens(token_ids, Role.ASSISTANT)
    except Exception:
        return {"role": "assistant", "content": fallback_text}

    if not parsed:
        return {"role": "assistant", "content": fallback_text}

    last = parsed[-1]
    recipient = getattr(last, "recipient", None)
    content_text = _stringify_harmony_content(last)

    if recipient is not None and "python" in str(recipient).lower():
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "python",
                        "arguments": json.dumps({"code": content_text}),
                    },
                }
            ],
        }
    return {"role": "assistant", "content": content_text}


def _stringify_harmony_content(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for blk in content:
            text = getattr(blk, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(blk, dict):
                t = blk.get("text") or blk.get("content")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return str(content) if content is not None else ""


__all__ = ["HarmonyClient"]
