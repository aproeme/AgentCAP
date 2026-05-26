"""Built-in delegation strategies.

To add a custom one:

    from agent_cap.agents import register_strategy, Strategy

    @register_strategy("my-strategy")
    class MyStrategy(Strategy):
        required_roles = ("scout", "worker")
        async def run(self, task, agents, tools):
            ...
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agent_cap.agents.agent import Agent
from agent_cap.agents.registry import register_strategy
from agent_cap.agents.tools import ToolProvider
from agent_cap.agents.types import RunResult, Task, Usage


class Strategy:
    """Base class for delegation strategies."""

    required_roles: Tuple[str, ...] = ()
    max_turns: int = 8

    def validate(self, agents: Dict[str, Agent]) -> None:
        missing = [r for r in self.required_roles if r not in agents]
        if missing:
            raise ValueError(
                f"Strategy '{type(self).__name__}' missing roles {missing}; "
                f"got {sorted(agents.keys())}"
            )

    async def run(
        self,
        task: Task,
        agents: Dict[str, Agent],
        tools: Optional[ToolProvider] = None,
    ) -> RunResult:
        raise NotImplementedError


def _collect(agents: Iterable[Agent]) -> Dict[str, Usage]:
    return {a.role: a.state.usage for a in agents}


def _all_turns(agents: Iterable[Agent]):
    out = []
    for a in agents:
        out.extend(a.state.turns)
    return out


@register_strategy("single")
class SingleAgentStrategy(Strategy):
    """One agent does everything (baseline)."""

    required_roles = ("agent",)

    async def run(self, task, agents, tools=None):
        self.validate(agents)
        agent = agents["agent"]
        if tools is not None and agent.tools is None and agent.spec.can_call_tools:
            agent.tools = tools
        t0 = time.perf_counter()
        await agent.run(task.user_prompt, max_turns=self.max_turns)
        return RunResult(
            task_id=task.task_id,
            strategy="single",
            output_text=agent.final_text(),
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage=_collect([agent]),
            turns=_all_turns([agent]),
        )


@register_strategy("plan-execute")
class PlanExecuteStrategy(Strategy):
    """Planner writes a plan once, executor carries it out with tools."""

    required_roles = ("planner", "executor")

    PLAN_PROMPT = (
        "You are a strategic planner. Produce a numbered, decision-complete plan "
        "for an executor agent. Name the exact tool to call at each step when a "
        "tool is needed. Do NOT execute the task yourself."
    )
    EXEC_PROMPT = (
        "You are a tool-using executor. Follow the plan step-by-step using the "
        "tools you have. After all steps, emit a final ANSWER line."
    )

    async def run(self, task, agents, tools=None):
        self.validate(agents)
        planner, executor = agents["planner"], agents["executor"]
        if not planner.spec.system_prompt:
            planner.state.messages.insert(0, {"role": "system", "content": self.PLAN_PROMPT})
        if not executor.spec.system_prompt:
            executor.state.messages.insert(0, {"role": "system", "content": self.EXEC_PROMPT})
        if tools is not None and executor.tools is None and executor.spec.can_call_tools:
            executor.tools = tools

        t0 = time.perf_counter()
        tool_summary = await _tool_summary(tools)
        planner.add_user(task.user_prompt + tool_summary)
        plan_turn = await planner.step(tool_schemas=None)
        plan_text = str(plan_turn.assistant.get("content") or "")

        exec_prompt = f"TASK: {task.user_prompt}\n\nPLAN:\n{plan_text}\n\nExecute it now."
        await executor.run(exec_prompt, max_turns=self.max_turns)

        return RunResult(
            task_id=task.task_id,
            strategy="plan-execute",
            output_text=executor.final_text(),
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage=_collect([planner, executor]),
            turns=_all_turns([planner, executor]),
            extras={"plan": plan_text},
        )


@register_strategy("supervisor")
class SupervisorStrategy(Strategy):
    """Supervisor delegates each turn to a worker. Stops when supervisor emits
    `DONE: <answer>` or max rounds is reached.

    Required roles: `supervisor`, plus one or more workers. Worker roles are any
    agents whose role != 'supervisor'. The supervisor picks the next worker by
    name (case-insensitive substring match) from its message; if no match, the
    first worker is used.
    """

    required_roles = ("supervisor",)
    max_rounds: int = 4

    async def run(self, task, agents, tools=None):
        self.validate(agents)
        supervisor = agents["supervisor"]
        workers = {role: a for role, a in agents.items() if role != "supervisor"}
        if not workers:
            raise ValueError("supervisor strategy requires at least one worker role")

        for w in workers.values():
            if tools is not None and w.tools is None and w.spec.can_call_tools:
                w.tools = tools

        if not supervisor.spec.system_prompt:
            roster = ", ".join(workers.keys())
            supervisor.state.messages.insert(0, {
                "role": "system",
                "content": (
                    "You are a supervisor coordinating workers. "
                    f"Workers available: {roster}. "
                    "Each turn, write a single line in the form\n"
                    "  DELEGATE <worker>: <instructions>\n"
                    "or, when you are confident in the final answer, write\n"
                    "  DONE: <final answer>"
                ),
            })

        t0 = time.perf_counter()
        supervisor.add_user(task.user_prompt)
        final_text = ""
        for _ in range(self.max_rounds):
            turn = await supervisor.step(tool_schemas=None)
            decision = str(turn.assistant.get("content") or "").strip()
            done, payload = _parse_supervisor_decision(decision)
            if done:
                final_text = payload
                break
            worker_name, instructions = _split_delegate(payload, list(workers.keys()))
            worker = workers[worker_name]
            await worker.run(instructions or task.user_prompt, max_turns=self.max_turns)
            worker_reply = worker.final_text()
            supervisor.state.messages.append({
                "role": "user",
                "content": f"[from {worker_name}] {worker_reply}",
            })

        if not final_text:
            final_text = supervisor.final_text()

        all_agents = [supervisor, *workers.values()]
        return RunResult(
            task_id=task.task_id,
            strategy="supervisor",
            output_text=final_text,
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage=_collect(all_agents),
            turns=_all_turns(all_agents),
        )


@register_strategy("sequential")
class SequentialStrategy(Strategy):
    """Pipe agents in a fixed order. Each receives the previous one's output.

    Configure the order via `--sequence role1,role2,...`. Defaults to the order
    of agents passed in.
    """

    required_roles = ()

    def __init__(self, sequence: Optional[List[str]] = None) -> None:
        self.sequence = sequence

    async def run(self, task, agents, tools=None):
        order = self.sequence or list(agents.keys())
        for role in order:
            if role not in agents:
                raise ValueError(f"sequence role '{role}' not in agents")

        t0 = time.perf_counter()
        current_input = task.user_prompt
        last_output = ""
        used_agents: List[Agent] = []
        for role in order:
            agent = agents[role]
            if tools is not None and agent.tools is None and agent.spec.can_call_tools:
                agent.tools = tools
            await agent.run(current_input, max_turns=self.max_turns)
            last_output = agent.final_text()
            current_input = last_output
            used_agents.append(agent)

        return RunResult(
            task_id=task.task_id,
            strategy="sequential",
            output_text=last_output,
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage=_collect(used_agents),
            turns=_all_turns(used_agents),
            extras={"order": order},
        )


async def _tool_summary(tools: Optional[ToolProvider]) -> str:
    if tools is None:
        return ""
    schemas = await tools.list_tools()
    if not schemas:
        return ""
    lines = []
    for t in schemas:
        fn = t.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "")
        if name:
            lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    return "\n\nAvailable tools:\n" + "\n".join(lines)


def _parse_supervisor_decision(text: str) -> Tuple[bool, str]:
    stripped = text.strip()
    if stripped.upper().startswith("DONE:"):
        return True, stripped[len("DONE:"):].strip()
    if stripped.upper().startswith("DELEGATE"):
        return False, stripped[len("DELEGATE"):].lstrip(": ").strip()
    return False, stripped


def _split_delegate(payload: str, worker_names: List[str]) -> Tuple[str, str]:
    head, sep, rest = payload.partition(":")
    head_norm = head.strip().lower()
    for name in worker_names:
        if name.lower() == head_norm or name.lower() in head_norm:
            return name, rest.strip()
    return worker_names[0], payload.strip()


__all__ = [
    "Strategy",
    "SingleAgentStrategy",
    "PlanExecuteStrategy",
    "SupervisorStrategy",
    "SequentialStrategy",
]
