# Extending the framework

Five extension points. All follow the same pattern: register a class in a
module, then load it with `--load-module DOTTED.PATH` from the CLI.

## 1. New Strategy

```python
# my_strats.py
import time
from agent_cap.agents import register_strategy, Strategy, RunResult


@register_strategy("debate")
class DebateStrategy(Strategy):
    required_roles = ("proposer", "opposer", "judge")
    max_turns = 6

    async def run(self, task, agents, tools=None):
        prop, opp, judge = agents["proposer"], agents["opposer"], agents["judge"]
        t0 = time.perf_counter()

        await prop.run(task.user_prompt, max_turns=self.max_turns)
        proposition = prop.final_text()

        await opp.run(f"Argue against:\n{proposition}", max_turns=self.max_turns)
        objection = opp.final_text()

        await judge.run(
            f"Question: {task.user_prompt}\n"
            f"Proposer said: {proposition}\n"
            f"Opposer said:  {objection}\n"
            "Decide and write a final ANSWER.",
            max_turns=self.max_turns,
        )

        return RunResult(
            task_id=task.task_id,
            strategy="debate",
            output_text=judge.final_text(),
            e2e_latency_s=time.perf_counter() - t0,
            per_role_usage={
                "proposer": prop.state.usage,
                "opposer":  opp.state.usage,
                "judge":    judge.state.usage,
            },
            turns=prop.state.turns + opp.state.turns + judge.state.turns,
        )
```

Use it:

```bash
python -m agent_cap.agents \
  --load-module my_strats --strategy debate \
  --agent proposer=name=... --agent opposer=name=... --agent judge=name=... \
  --task "Is P=NP?"
```

## 2. New LLM protocol

See [protocols.md](protocols.md#adding-a-new-protocol).

## 3. New ToolProvider

A ToolProvider is anything with `async list_tools()` and
`async call(name, args)`. To plug it into the CLI you have two options.

### Option A: register Python callables on a `LocalToolRegistry`

```python
# my_tools.py
from agent_cap.agents.tools import LocalToolRegistry

reg = LocalToolRegistry()


@reg.tool(
    name="web_search",
    description="Search the web with Brave Search.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)
def web_search(query: str) -> str:
    # call your API ...
    return "results"
```

Then wire `reg` into a config or hand it to `_build_tools` from your own
runner.

### Option B: full-blown adapter (preferred for external backends)

```python
# my_tools.py
from typing import Any, Dict, List


class WikipediaProvider:
    async def list_tools(self) -> List[Dict[str, Any]]:
        return [{
            "type": "function",
            "function": {
                "name": "wiki_lookup",
                "description": "Fetch first paragraph from Wikipedia.",
                "parameters": {"type": "object", "properties": {"page": {"type": "string"}}, "required": ["page"]},
            },
        }]

    async def call(self, name: str, arguments: Dict[str, Any]) -> str:
        page = arguments.get("page", "")
        # fetch & return text
        return "..."

    async def teardown(self):
        pass
```

To expose it as a CLI flag you currently add a branch in
`agents/cli.py::_resolve_tools`. (The tool-backend list does not yet have a
public decorator. If you need one, ask.)

## 4. New Evaluator

```python
# my_evals.py
from typing import Any, Dict

from agent_cap.agents import register_evaluator, EvalResult


@register_evaluator("rouge-l")
class RougeLEvaluator:
    def __init__(self, threshold: float = 0.5, **_: Any) -> None:
        self.threshold = threshold

    def evaluate(self, task_meta: Dict[str, Any], output_text: str) -> EvalResult:
        gold = str(task_meta.get("answer") or "")
        # compute rouge-l score ...
        score = 0.0
        passed = score >= self.threshold
        return EvalResult(
            passed=passed, score=score,
            details={"evaluator": "rouge-l", "threshold": self.threshold},
        )
```

Use it:

```bash
python -m agent_cap.agents \
  --load-module my_evals --evaluator rouge-l \
  ...
```

Constructor kwargs that come from `--judge k=v,k=v` or YAML `judge:` flow
into your `__init__`, so you can accept arbitrary config the same way the
built-in `llm-judge` does.

## 5. New agent topology

If the role/agent decoupling (pool + roles + replicas) does not
cover what you need, write a Strategy. The Strategy receives `{role: Agent}`
and is free to call them in any order, with any messages, sharing state
however you want by manually copying `agent.state.messages`.

## Loading multiple modules

```bash
python -m agent_cap.agents \
  --load-module my_strats \
  --load-module my_evals \
  --load-module my_protocols \
  --strategy debate --evaluator rouge-l \
  ...
```

Order does not matter; each module is imported once before resolution.
