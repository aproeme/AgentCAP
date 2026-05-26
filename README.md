# AgentCAP

Benchmarking framework for AI agent systems — measures **Cost**, **Accuracy**,
and **Performance** of single-agent and multi-agent workloads across multiple
benchmarks (IMO AnswerBench, MCP-ATLAS, MedAgentBench, FinanceBench, SWE-Bench).

## Install

```bash
git clone https://github.com/Auto-CAP/AgentCAP.git
cd AgentCAP
git checkout v1_beta
git submodule update --init --recursive
pip install -e .
```

## Quickstart

### Tool-use benchmark — MCP-ATLAS on Qwen3.5

Serve the model with tool-call parser:

```bash
vllm serve Qwen/Qwen3.5-4B \
  --served-model-name openai/Qwen3.5-4B \
  --port 30000 \
  --max-model-len 65536 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder
```

Start the MCP tool server (in another terminal):

```bash
bash mcp-server/start.sh
```

Run the benchmark:

```bash
python -m agent_cap.agents \
  --strategy single \
  --model openai/Qwen3.5-4B \
  --base-url http://localhost:30000/v1 \
  --api-key dummy \
  --dataset mcp-atlas \
  --evaluator gtfa \
  --tool-backend mcp --mcp-server-url http://localhost:1984 \
  --num-tasks 30 \
  --output-dir results/mcp
```

### Reasoning benchmark — IMO AnswerBench via Harmony (gpt-oss)

For models that need client-side Harmony token decoding (gpt-oss family +
fine-grained `reasoning_effort`), use the bundled config:

```bash
python -m agent_cap.agents --config configs/agents_imo_gptoss_sglang.yaml
```

That config sets `protocol: harmony`, `engine: sglang`, and points at a local
sglang server. See [docs/agents/protocols.md](docs/agents/protocols.md) for
when to opt into Harmony vs. the default OpenAI-compatible path.

### Mock mode

No LLM, no GPU — sanity check the framework:

```bash
python -m agent_cap.agents --mock --strategy plan-execute --task "compute 1+1"
```

## Documentation

| File | Topic |
|---|---|
| [docs/datasets.md](docs/datasets.md) | All 5 datasets (imo, mcp-atlas, medagent, finance, swe-bench) — command per dataset |
| [docs/mcp-server.md](docs/mcp-server.md) | Self-host MCP server without Docker (`mcp-server/start.sh`) |
| [docs/RUN_NO_DOCKER.md](docs/RUN_NO_DOCKER.md) | SWE-Bench Lite via Modal (no Docker needed locally) |
| [docs/agents/concepts.md](docs/agents/concepts.md) | Agent / Strategy / Protocol / Tool / Evaluator |
| [docs/agents/cli.md](docs/agents/cli.md) | All CLI flags and precedence |
| [docs/agents/yaml.md](docs/agents/yaml.md) | YAML config: pool, roles, replicas, includes |
| [docs/agents/strategies.md](docs/agents/strategies.md) | Built-in strategies: single, plan-execute, supervisor, sequential |
| [docs/agents/protocols.md](docs/agents/protocols.md) | LLM protocols (openai default, harmony opt-in, mock) |
| [docs/agents/serving.md](docs/agents/serving.md) | vLLM / sglang launch flags per model family |
| [docs/agents/extending.md](docs/agents/extending.md) | Recipes for custom strategies, protocols, tools, evaluators |

## Acknowledgement

This project is supported by the Advanced Research and Invention Agency (ARIA)'s
grant *"Scaling Compute: AI at 1/1000th the cost. Technical Area 4 Benchmarking"*.
