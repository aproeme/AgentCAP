from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import aiohttp

from agent_cap.agents.llm.base import LLMReply
from agent_cap.agents.llm.registry import register_protocol
from agent_cap.agents.types import ModelEndpoint, Usage


@register_protocol("openai", default=True)
class OpenAIChatClient:
    """Standard OpenAI-compatible /v1/chat/completions client.

    Default protocol. Works for OpenAI, OpenRouter, sglang, vLLM (without
    harmony), Ollama, LM Studio, llama.cpp server, etc.
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, **_: Any) -> None:
        self._session = session

    async def chat(
        self,
        endpoint: ModelEndpoint,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMReply:
        from agent_cap.runner.llm_client import _chat_with_fallback, _to_int

        if self._session is None:
            raise RuntimeError(
                "OpenAIChatClient requires an aiohttp.ClientSession. "
                "Construct it inside `async with aiohttp.ClientSession() as session:`."
            )

        errors: List[str] = []
        t0 = time.perf_counter()
        timed = await _chat_with_fallback(
            session=self._session,
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=endpoint.name,
            messages=messages,
            tools=tools,
            max_tokens=endpoint.max_tokens,
            temperature=endpoint.temperature,
            openrouter_provider=endpoint.openrouter_provider,
            use_streaming=endpoint.use_streaming,
            errors=errors,
        )
        elapsed = time.perf_counter() - t0
        resp = timed.response_json or {}
        choices = resp.get("choices") or []
        assistant = (choices[0].get("message") if choices else {}) or {}
        if "role" not in assistant:
            assistant["role"] = "assistant"
        usage_raw = resp.get("usage") or {}
        usage = Usage(
            input_tokens=_to_int(usage_raw.get("prompt_tokens", timed.input_tokens)),
            output_tokens=_to_int(usage_raw.get("completion_tokens", timed.output_tokens)),
            cached_tokens=_to_int(usage_raw.get("cached_tokens", timed.cached_tokens)),
            requests=1,
        )
        return LLMReply(assistant=assistant, usage=usage, latency_s=elapsed, raw=resp)


__all__ = ["OpenAIChatClient"]
