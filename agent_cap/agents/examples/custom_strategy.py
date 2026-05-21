"""Example: how to add a custom strategy.

Run it with:

    python -m agent_cap.agents \
        --load-module agent_cap.agents.examples.custom_strategy \
        --strategy critic-loop \
        --mock --task "draft a slogan for a coffee brand"
"""

from __future__ import annotations

import time

from agent_cap.agents import RunResult, Strategy, register_strategy


@register_strategy("critic-loop")
class CriticLoopStrategy(Strategy):
    """Drafter writes, critic revises N times, drafter rewrites once at the end."""

    required_roles = ("drafter", "critic")
    rounds: int = 2

    async def run(self, task, agents, tools=None):
        self.validate(agents)
        drafter, critic = agents["drafter"], agents["critic"]

        t0 = time.perf_counter()
        await drafter.run(task.user_prompt, max_turns=self.max_turns)
        current = drafter.final_text()
        for _ in range(self.rounds):
            await critic.run(f"Critique and improve:\n{current}", max_turns=self.max_turns)
            current = critic.final_text()

        await drafter.run(f"Final polish based on this critique:\n{current}",
                          max_turns=self.max_turns)
        final = drafter.final_text()

        return RunResult(
            task_id=task.task_id,
            strategy="critic-loop",
            output_text=final,
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage={
                "drafter": drafter.state.usage,
                "critic": critic.state.usage,
            },
            turns=drafter.state.turns + critic.state.turns,
        )
