#!/usr/bin/env python3
"""Idempotently rewrite a SWE-agent checkout's `sweagent/agent/models.py` so
its single litellm.completion call goes through agent_cap.sweagent_streaming
(aiohttp-based streaming with TTFT/TPOT/usage capture).

Usage: python scripts/patch_sweagent_streaming.py /path/to/SWE-agent
"""
import sys
from pathlib import Path

MARKER = "AGENTCAP_STREAMING_PATCH_APPLIED"

ORIG_BLOCK = """        try:
            response: litellm.types.utils.ModelResponse = litellm.completion(  # type: ignore
                model=self.config.name,
                messages=messages,
                temperature=self.config.temperature if temperature is None else temperature,
                top_p=self.config.top_p,
                api_version=self.config.api_version,
                api_key=self.config.choose_api_key(),
                fallbacks=self.config.fallbacks,
                **completion_kwargs,
                **extra_args,
                n=n,
            )"""

NEW_BLOCK = """        try:
            # AGENTCAP_STREAMING_PATCH_APPLIED: route through agent_cap.sweagent_streaming
            # to get per-call TTFT/TPOT, visible/reasoning/cached token split.
            from agent_cap.sweagent_streaming import completion_streaming as _agentcap_completion_streaming
            _agentcap_extra_body = completion_kwargs.pop("extra_body", None)
            _agentcap_extra_headers = completion_kwargs.pop("extra_headers", None)
            response = _agentcap_completion_streaming(
                model=self.config.name,
                messages=messages,
                temperature=self.config.temperature if temperature is None else temperature,
                top_p=self.config.top_p,
                api_base=extra_args.get("api_base"),
                api_key=self.config.choose_api_key(),
                tools=extra_args.get("tools"),
                extra_body=_agentcap_extra_body,
                extra_headers=_agentcap_extra_headers,
            )"""


def patch(sweagent_dir: Path) -> int:
    models_py = sweagent_dir / "sweagent" / "agent" / "models.py"
    if not models_py.exists():
        print(f"ERROR: {models_py} not found", file=sys.stderr)
        return 2
    text = models_py.read_text()
    if MARKER in text:
        print(f"already patched: {models_py}")
        return 0
    if ORIG_BLOCK not in text:
        print(
            f"ERROR: original litellm.completion(...) block not found in {models_py}. "
            "Has the upstream code drifted? Edit the script's ORIG_BLOCK to match.",
            file=sys.stderr,
        )
        return 3
    new_text = text.replace(ORIG_BLOCK, NEW_BLOCK, 1)
    models_py.write_text(new_text)
    print(f"patched: {models_py}")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    return patch(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    sys.exit(main())
