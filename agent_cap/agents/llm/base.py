from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from agent_cap.agents.types import ModelEndpoint, Usage


@dataclass
class LLMReply:
    assistant: Dict[str, Any]
    usage: Usage
    latency_s: float
    raw: Dict[str, Any]
    ttft_s: float = 0.0
    decode_s: float = 0.0


class LLMClient(Protocol):
    async def chat(
        self,
        endpoint: ModelEndpoint,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMReply: ...


__all__ = ["LLMReply", "LLMClient"]
