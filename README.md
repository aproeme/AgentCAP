# AgentCAP

Benchmarking framework for AI agent systems — measuring **Cost**, **Accuracy**, and **Performance** across single-agent and multi-agent workloads.

## Architecture

```
agent_cap/
├── core/                  # Shared core
│   ├── agentic_loop.py    # LLM → tool calls → metrics (TTFT, TPOT, tokens)
│   ├── tool_backend.py    # Abstract ToolBackend interface
│   ├── evaluator.py       # Abstract Evaluator interface
│   └── metrics.py         # BenchmarkMetrics aggregation
├── backends/              # Tool execution backends (pluggable)
│   ├── swebench_backend   # Docker/Modal sandbox (SWE-bench Pro)
│   └── mcp_backend        # MCP server HTTP API (MCP-ATLAS)
├── evaluators/            # Evaluation methods (pluggable)
│   ├── swebench_eval      # run_script.sh + parser.py
│   └── gtfa_eval          # GTFA claims
├── workloads/             # Workload types
│   ├── single_agent       # 1 model autonomous loop
│   └── agent_team         # Planner + Executor (plan-execute)
└── server/
    └── streaming_client   # aiohttp SSE streaming (TTFT/TPOT)
```

## Supported Benchmarks

| Benchmark | Dataset | Tools | Evaluation |
|---|---|---|---|
| **SWE-bench Pro** | `ScaleAI/SWE-bench_Pro` | read/write/shell/search in Docker/Modal | run_script.sh per instance |
| **MCP-ATLAS** | `ScaleAI/mcp-atlas` | GitHub, fetch, whois via MCP server | GTFA claims |

## Workload Types

| Workload | Description |
|---|---|
| **Single Agent** | One model autonomously reads code, writes fixes, runs tests |
| **Agent Team** | Planner model creates step-by-step plan, Executor model follows it with tool calls |

## Metrics Collected

- **User-facing**: E2E latency (avg/p50/p99), Requests per second
- **Inference**: TTFT avg/p99, TPOT avg/p99
- **Agentic**: Total input/output tokens, tool call count, avg tool call latency
- **Hardware**: GPU utilization, CPU utilization

## Quick Start

### SWE-bench Pro (Single Agent)

```bash
pip install -e ".[all]"

# Start vLLM
vllm serve unsloth/GPT-OSS-120b --port 8000

# Run benchmark (Modal runtime for RunPod)
agent-cap single-agent configs/single_agent_with_tools.yaml \
    --runtime modal --limit 5 --max-turns 10
```

### MCP-ATLAS

```bash
# Start MCP server
docker run --rm -d --name mcp-atlas-env -p 1984:1984 mcp-atlas-env

# Run benchmark
agent-cap mcp-atlas configs/mcp_atlas.yaml --limit 10
```

### Agent Team (Plan-Execute)

```bash
# Start two models
vllm serve planner-model --port 8000
vllm serve executor-model --port 8001

# Run via workloads/agent_team.py
python scripts/run_hybrid_experiment.py --config configs/hybrid_config.yaml
```

## Adding a New Benchmark

1. Implement `ToolBackend` (how tools execute)
2. Implement `Evaluator` (how to judge results)
3. Both workloads (`single_agent`, `agent_team`) work automatically

## Unified agent CLI: `agent_cap.agents` (v1_beta)

Lightweight, extensible runtime that unifies single-agent and multi-agent
runs behind one CLI. Auto-routes OpenAI / Harmony (gpt-oss) / mock protocols
based on model name; vLLM and sglang serving engines are both supported.

```bash
# Smoke test (no API key)
python -m agent_cap.agents --mock --strategy plan-execute --task "1+1"

# One model, OpenAI-compatible endpoint
python -m agent_cap.agents --strategy single \
  --agent agent=name=Qwen/Qwen2.5-72B-Instruct,base_url=http://localhost:30000/v1,api_key=EMPTY \
  --dataset imo-answerbench --num-tasks 5 \
  --tool-backend math-python --evaluator imo \
  --output-dir results/qwen_imo --resume

# gpt-oss on sglang via harmony protocol
python -m agent_cap.agents --strategy single \
  --agent agent=name=gpt-oss-120b,base_url=http://localhost:30000,api_key=EMPTY,engine=sglang \
  --dataset imo-answerbench --tool-backend math-python --evaluator imo

# LLM as a judge
python -m agent_cap.agents --strategy single \
  --agent agent=name=Qwen/Qwen2.5-7B-Instruct,base_url=...,api_key=... \
  --evaluator llm-judge \
  --judge "name=gpt-4o,base_url=https://api.openai.com/v1,api_key=$OPENAI_API_KEY"
```

Full reference under [`docs/agents/`](docs/agents/):

| File | Topic |
|---|---|
| [docs/agents/cli.md](docs/agents/cli.md) | All CLI flags and precedence |
| [docs/agents/yaml.md](docs/agents/yaml.md) | YAML config: agents pool, roles, replicas, share_state, includes |
| [docs/agents/concepts.md](docs/agents/concepts.md) | Agent, Strategy, Protocol, Tool, Evaluator |
| [docs/agents/strategies.md](docs/agents/strategies.md) | Built-in strategies in depth: single, plan-execute, supervisor, sequential |
| [docs/agents/protocols.md](docs/agents/protocols.md) | LLM protocols (openai/harmony/mock), auto-routing, adding new |
| [docs/agents/serving.md](docs/agents/serving.md) | vLLM / sglang launch commands per model family and tool-parser flags |
| [docs/agents/extending.md](docs/agents/extending.md) | Recipes for custom strategies, protocols, tools, evaluators |

## Acknowledgement

This project is supported by the Advanced Research and Invention Agency (ARIA)'s grant "Scaling Compute: AI at 1/1000th the cost. Technical Area 4 Benchmarking".
