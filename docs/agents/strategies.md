# Strategies

A `Strategy` decides how one or more `Agent`s coordinate to solve a task.
The framework ships with four. All are interchangeable through the same CLI:

```bash
python -m agent_cap.agents --strategy NAME ...
```

Source: `agent_cap/agents/strategies.py`.

---

## `single`

**One agent does the whole task.**

```
task ---> agent (loop: think -> tool? -> think -> ...) ---> final answer
```

| | |
|---|---|
| Required roles | `agent` |
| Outputs | `per_role_usage = {"agent": {...}}` |
| Tool access | The agent uses the shared tool provider directly. |
| Termination | Agent emits a turn with no `tool_calls`, OR `max_turns` reached. |

### When to use

- Baseline ("what does one model score?"). Always run this first.
- Tasks where a single model has enough context + tool budget to finish.

### When NOT to use

- Long reasoning chains where you want to split planning from execution
  (use `plan-execute`).
- Tasks needing >1 distinct specialization (use `supervisor` or `sequential`).

### CLI

```bash
python -m agent_cap.agents --strategy single \
  --model Qwen/Qwen2.5-72B-Instruct \
  --base-url http://localhost:30000/v1 --api-key EMPTY \
  --dataset imo-answerbench --num-tasks 5 \
  --tool-backend math-python --evaluator imo \
  --output-dir results/single_qwen
```

### YAML

```yaml
strategy: single
agents:
  agent:
    name: Qwen/Qwen2.5-72B-Instruct
    base_url: http://localhost:30000/v1
    api_key: EMPTY
dataset: imo-answerbench
tool_backend: math-python
evaluator: imo
output_dir: results/single_qwen
```

---

## `plan-execute`

**Planner writes a fixed plan once; executor follows it with tools.**

```
task ---> planner (no tools, one LLM call) ---> plan text
                                                    |
                                                    v
                                           executor (tool loop) ---> final answer
```

| | |
|---|---|
| Required roles | `planner`, `executor` |
| Outputs | `per_role_usage = {"planner": {...}, "executor": {...}}` and `extras.plan` |
| Tool access | Only `executor` uses tools. Planner sees the tool list in its prompt but never calls one. |
| Termination | Executor's loop stops (empty `tool_calls` or `max_turns`). |

### Default prompts

Used when `system_prompt` is not set on the spec:

- **Planner**: "produce a numbered decision-complete plan; name each tool to call; do NOT execute the task yourself."
- **Executor**: "follow the plan step-by-step; emit a final ANSWER line."

Both are overridable per-agent via `--system-prompt` or YAML `system_prompt:`.

### When to use

- Long-horizon tasks where one big planner-side think pass beats interleaved
  small thinks.
- Compute split: small/cheap planner + larger executor (or vice versa).
- You want a separable plan to inspect / score on its own.

### When NOT to use

- Tasks where the plan needs to adapt mid-execution to tool output. The
  plan is written once before any tool runs. Use `supervisor` for adaptive
  delegation.
- Trivial tasks where a 2-call overhead is wasted.

### CLI

```bash
python -m agent_cap.agents --strategy plan-execute \
  --agent planner=name=Qwen/Qwen2.5-72B-Instruct,base_url=http://localhost:30000/v1,api_key=EMPTY \
  --agent executor=name=gpt-oss-120b,base_url=http://localhost:8000,api_key=EMPTY,engine=sglang,max_tokens=131072 \
  --dataset imo-answerbench --tool-backend math-python --evaluator imo \
  --output-dir results/plan_qwen_exec_gptoss
```

### YAML

```yaml
strategy: plan-execute
agents:
  planner:
    name: Qwen/Qwen2.5-72B-Instruct
    base_url: http://localhost:30000/v1
    api_key: EMPTY
  executor:
    name: gpt-oss-120b
    base_url: http://localhost:8000
    api_key: EMPTY
    engine: sglang
    max_tokens: 131072
dataset: imo-answerbench
tool_backend: math-python
evaluator: imo
```

### Result extras

```json
{
  "extras": {
    "plan": "1. Use python tool to compute integral...\n2. Verify result via..."
  }
}
```

---

## `supervisor`

**Supervisor delegates each turn to a named worker; stops on `DONE:`.**

```
task -> supervisor -> "DELEGATE worker_A: do X"
            ^                       |
            |                       v
            +--- "[from worker_A] result" <-- worker_A (own tool loop)

    ... up to max_rounds ...

   supervisor -> "DONE: <final answer>"  ->  return
```

| | |
|---|---|
| Required roles | `supervisor` + one or more worker roles (any name != "supervisor") |
| Outputs | `per_role_usage` has one entry per worker used + supervisor |
| Tool access | Workers use tools. Supervisor does not call tools directly. |
| Termination | Supervisor emits a line starting with `DONE:` (case-insensitive), OR `max_rounds` reached. |

### Decision protocol

Supervisor each turn writes ONE line in one of two forms (matched
case-insensitively):

```
DELEGATE <worker_name>: <instructions>
DONE: <final answer>
```

Worker selection: substring match on `<worker_name>`. If no match, the first
worker is used.

### Default supervisor prompt

```
You are a supervisor coordinating workers.
Workers available: researcher, coder, writer
Each turn, write a single line in the form
  DELEGATE <worker>: <instructions>
or, when you are confident in the final answer, write
  DONE: <final answer>
```

Override with `--system-prompt` or YAML.

### When to use

- Adaptive workflows where the next sub-task depends on previous results.
- Tasks decomposable into independent sub-tasks routed to specialized agents.
- Research-style work: gather, analyze, summarize, each by a different model.

### When NOT to use

- Linear pipelines with no branching (use `sequential`).
- Cost-sensitive runs: every round is one supervisor call PLUS one worker
  run. Easily 3-5x more expensive than `single` on the same task.
- Short tasks where the supervisor's decision overhead exceeds the work.

### Parameters

- `max_rounds` (default 4) — how many supervisor turns before the loop exits.
  Set in the strategy code or via subclass; not yet a CLI flag.

### CLI

```bash
python -m agent_cap.agents --strategy supervisor \
  --agent supervisor=name=gpt-4o,base_url=https://api.openai.com/v1,api_key=$OAI \
  --agent researcher=name=gpt-4o-mini,base_url=https://api.openai.com/v1,api_key=$OAI,system_prompt="Find facts." \
  --agent coder=name=Qwen/Qwen2.5-72B,base_url=http://localhost:30000/v1,api_key=EMPTY,system_prompt="Write code." \
  --task "Compare attention vs RNN throughput; write a code benchmark to verify."
```

### YAML

```yaml
strategy: supervisor
agents:
  supervisor:
    name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
  researcher:
    name: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Find authoritative facts. Cite sources."
  coder:
    name: Qwen/Qwen2.5-72B-Instruct
    base_url: http://localhost:30000/v1
    api_key: EMPTY
    system_prompt: "Write and execute Python. Verify with the python tool."
task: "Compare attention vs RNN throughput experimentally."
```

### Scaling out workers (replicas)

```yaml
strategy: supervisor

agents:
  big:
    name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
  small:
    name: Qwen/Qwen2.5-7B-Instruct
    base_url: "http://localhost:3010{i}/v1"
    api_key: EMPTY
    replicas: 100              # expands to small-0 .. small-99

roles:
  supervisor: big
  worker-{i}:
    agent: small-{i}
    replicas: 100              # worker-0 -> small-0, ..., worker-99 -> small-99
```

Supervisor sees 100 worker names and routes each delegation by substring
match.

---

## `sequential`

**Pipe agents in a fixed order; each receives the previous one's output.**

```
task -> role_1 -> output_1 -> role_2 -> output_2 -> role_3 -> final
```

| | |
|---|---|
| Required roles | At least one; order set by `--sequence r1,r2,...` or YAML role insertion order. |
| Outputs | `per_role_usage` has one entry per role in the sequence |
| Tool access | Each agent has access to the shared tool provider for its own loop. |
| Termination | After the last agent in the sequence finishes. No back-tracking. |

### Behavior

- The very first agent receives `task.user_prompt`.
- Every subsequent agent receives the previous agent's `final_text()` as a
  user message.
- Each agent runs its OWN tool-use loop (up to `max_turns`).
- Each agent keeps its own conversation state; communication happens via the
  user message that carries the previous agent's `final_text()`.

### When to use

- Genuinely sequential workflows: write → critique → polish, extract → cluster
  → summarize, translate → review.
- Each stage benefits from a different prompt or model.
- You DO NOT need the next stage to influence earlier stages.

### When NOT to use

- Iterative refinement loops (use a custom strategy or `supervisor`).
- Stages where role_2 needs to see the original task AND role_1's output
  separately (currently sees only role_1's output as a fresh user message).

### CLI

```bash
python -m agent_cap.agents --strategy sequential \
  --sequence writer,critic,polisher \
  --agent writer=name=gpt-4o,base_url=...,api_key=...,system_prompt="Write a draft." \
  --agent critic=name=claude-3.5-sonnet,base_url=...,api_key=...,system_prompt="List 3 problems." \
  --agent polisher=name=gpt-4o,base_url=...,api_key=...,system_prompt="Rewrite using the critique." \
  --task "An essay about why transformers work."
```

### YAML

```yaml
strategy: sequential
sequence: [writer, critic, polisher]   # optional; defaults to YAML order

agents:
  writer:
    name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Write a first draft. ~300 words."
  critic:
    name: claude-3.5-sonnet
    base_url: https://api.anthropic.com/v1
    api_key: ${ANTHROPIC_API_KEY}
    system_prompt: "List 3 problems with the draft. No rewriting."
  polisher:
    name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Rewrite the draft addressing the critique."

task: "Why do transformers work in 300 words."
```

`sequence` is repeatable; specify role order explicitly when YAML insertion
order is not what you want.

### Result extras

```json
{
  "extras": {
    "order": ["writer", "critic", "polisher"]
  }
}
```

---

## At-a-glance comparison

|  | `single` | `plan-execute` | `supervisor` | `sequential` |
|---|---|---|---|---|
| Required roles | 1 | 2 (planner+executor) | 1 + N | N (any) |
| Coordination | none | one-shot plan -> exec | adaptive delegation per round | fixed pipeline |
| Calls per task (typical) | 1-10 | 1 + 1-10 | 4 * 2 = ~8 | N * 1-5 |
| Cost vs `single` | 1x | 1.1-1.5x | 3-5x | Nx |
| Right when | baseline / one model is enough | planning helps + you want plan visible | sub-tasks decided dynamically | linear write-critique-polish stages |

## Adding your own

See [extending.md](extending.md#1-new-strategy) for the recipe. The full
contract is:

```python
class Strategy:
    required_roles: Tuple[str, ...] = ()
    max_turns: int = 8

    async def run(
        self,
        task: Task,
        agents: Dict[str, Agent],
        tools: Optional[ToolProvider] = None,
    ) -> RunResult: ...
```

Register with `@register_strategy("name")` and load via
`--load-module dotted.path`.
