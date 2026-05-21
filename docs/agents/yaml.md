# YAML configuration

Two equivalent layouts. Pick by use case.

## Layout A: inline (simple, 1:1 role:agent)

`agents:` keys ARE strategy role names. Pre-existing AgentCAP configs follow
this shape.

```yaml
strategy: plan-execute
demo_tools: true

defaults:                # optional; merged into every agent
  api_key: EMPTY
  max_tokens: 4096
  temperature: 0.0

agents:
  planner:
    name: Qwen/Qwen2.5-72B-Instruct
    base_url: http://localhost:30000/v1
  executor:
    name: Qwen/Qwen2.5-7B-Instruct
    base_url: http://localhost:30001/v1

task: "Compute (12 + 8) / 4."
```

## Layout B: pool + roles (decoupled, supports N:1 and sharing)

`agents:` is a pool of endpoint definitions; `roles:` maps strategy positions
to those names. Multiple roles can point to the same pool entry.

```yaml
strategy: plan-execute

agents:                  # pool. Keys are arbitrary names.
  big:
    name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
  small:
    name: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}

roles:                   # strategy role -> agent name
  planner: big
  executor: small
  # critic: big          # N:1 endpoint sharing
```

## Replicas

Expand one entry to many. `{i}` in `name`, `base_url`, or role keys is replaced
with the instance index.

```yaml
agents:
  worker:
    name: Qwen/Qwen2.5-7B-Instruct
    base_url: "http://localhost:3010{i}/v1"
    api_key: EMPTY
    replicas: 100        # -> worker-0 .. worker-99
```

In layout B, role replicas:

```yaml
agents:
  small:
    name: Qwen/Qwen2.5-7B-Instruct
    base_url: "http://localhost:3010{i}/v1"
    replicas: 100        # pool: small-0 .. small-99

roles:
  worker-{i}:
    agent: small-{i}
    replicas: 100        # worker-0 -> small-0, worker-99 -> small-99
```

## Sharing conversation state

By default, two roles pointing to the same agent get separate `Agent`
instances (same endpoint, independent message histories).

To share one instance (joint conversation):

```yaml
roles:
  planner: gpt4o
  critic:  gpt4o

share_state:
  - [planner, critic]    # one Agent, one history
```

## Includes

```yaml
include:
  - ../specs/planner.yaml
  - ../specs/workers_gpu0.yaml

agents:                  # top-level wins over included files
  planner:
    temperature: 0.7
```

## Top-level fields

| Field | Purpose |
|---|---|
| `strategy` | Strategy name. |
| `agents` | Pool. |
| `roles` | Role -> agent mapping (optional, enables layout B). |
| `share_state` | List of role-group lists. |
| `defaults` | Fields merged into every agent in `agents:`. |
| `include` | Recursive YAML files to merge. |
| `task` / `tasks` | Inline task(s). |
| `dataset` / `num_tasks` | Use AgentCAP datasets via `unified_runner`. |
| `tool_backend` | `mcp` / `math-python` / `demo`. |
| `mcp_server_url` | For `tool_backend: mcp`. |
| `evaluator` | `exact` / `gtfa` / `imo` / `llm-judge` / `none`. |
| `judge` | Config block for `llm-judge`. |
| `demo_tools` | Bool. Adds built-in `calc`/`echo` tools. |
| `output_dir` | Where to write results. |
| `max_turns` | Tool-use turns per agent. |

## Environment variables

Any `${VAR}` or `$VAR` in a YAML string is expanded at load time
(`os.path.expandvars`).
