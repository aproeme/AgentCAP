# Concepts

Five orthogonal pieces. Each is replaceable through a registry.

```
              +----------------+
              |   Strategy     |    plan-execute, supervisor, ...
              |   (topology)   |    @register_strategy
              +-------+--------+
                      |
              spawns N Agents
                      |
       +--------------+--------------+
       |              |              |
   +---v---+      +---v---+      +---v---+
   | Agent |      | Agent |      | Agent |   one role each
   +-------+      +-------+      +-------+
       |              |              |
       | uses         | uses         | uses
       v              v              v
   +-------+      +-------+      +-------+
   |  LLM  |      |  LLM  |      |  LLM  |   one Protocol per agent
   | Proto |      | Proto |      | Proto |   @register_protocol
   +-------+      +-------+      +-------+
       \              |              /
        \             |             /
         \            v            /
          \      +---------+      /
           +--->|  Tools  |<----+      one ToolProvider, shared
                +----+----+
                     |
                     v
              (executes side-effects)

      After all agents finish:
              +-----------+
              | Evaluator |   exact / gtfa / imo / llm-judge
              +-----------+   @register_evaluator
```

## Agent

`agents/agent.py`. One role with its own message history, driven by one
`LLMClient`. Has `step()` (one LLM call, no tool exec) and `run(prompt)`
(full tool-use loop). Doesn't know about strategies.

## Strategy

`agents/strategies.py`. Orchestrates one or more Agents to solve a task.
Built-ins:

- `single` — one agent.
- `plan-execute` — planner writes a plan, executor follows it.
- `supervisor` — supervisor delegates each turn to a worker; stops on `DONE:`.
- `sequential` — pipe agents in a fixed order, each gets the previous output.

A Strategy declares `required_roles` and implements `async run(task, agents, tools)`.

See [strategies.md](strategies.md) for per-strategy behavior, when-to-use,
when-not-to-use, CLI and YAML examples, and the at-a-glance comparison.

## Protocol (LLM client)

`agents/llm/`. Speaks to one model endpoint.

- `openai` (default) — OpenAI-compatible `/v1/chat/completions`. Covers OpenAI,
  OpenRouter, sglang, vLLM (when chat-completions is enabled), Ollama, etc.
- `harmony` — gpt-oss family. Token-level encoding via `openai_harmony`, calls
  `/v1/completions`.
- `mock` — deterministic offline LLM for testing.

Auto-routing reads `endpoint.name` against each protocol's `model_pattern`.
Override per agent with `protocol=harmony` in `--agent ...` or YAML.

## ToolProvider

`agents/tools.py` defines the protocol:

```python
class ToolProvider(Protocol):
    async def list_tools(self) -> list[dict]:    # OpenAI tool schemas
    async def call(self, name, arguments) -> str:
```

Built-in providers via `--tool-backend`:

- `demo` — `calc` + `echo`, for smoke tests.
- `mcp` — wraps `agent_cap.runner.tool_backends.MCPToolBackend`.
- `math-python` — wraps `agent_cap.backends.math_python_backend.MathPythonBackend`
  (Jupyter kernel, used by IMO).

## Evaluator

`agents/evaluators.py`. After a strategy finishes, an evaluator scores the
final output text against task metadata.

- `none` — no scoring.
- `exact` — string equality with `task_meta["answer"]`.
- `gtfa` — wraps `agent_cap.evaluators.gtfa_eval.GTFAEvaluator`.
- `imo` / `imo-answerbench` — boxed extraction + `math_verify` + OpenRouter
  fallback.
- `llm-judge` / `judge` — generic LLM-as-a-judge against any OpenAI-compatible
  endpoint, configurable via `--judge k=v,k=v` or YAML `judge:`.

## How they interact in one run

1. CLI/YAML parsed into `AgentSpec`s and a strategy name.
2. For each agent, the protocol registry picks an `LLMClient` based on
   `endpoint.name` (or explicit `protocol=`).
3. One shared `ToolProvider` is built (or `None`).
4. The selected strategy gets `{role -> Agent}` and the tool provider.
5. For each task, the strategy runs. The final `RunResult` is serialized.
6. If `--evaluator` is set, the evaluator scores `RunResult.output_text`.
7. Results stream to `<output-dir>/results.jsonl`. With `--resume`, finished
   `task_id`s are skipped.
