# agents_track_b — Track B LangGraph Pipeline

**Source:** `src/agents/agents_track_b.py`

## Purpose
LangGraph `StateGraph` implementing the full Track B pipeline. Handles all three task types: `TOPOLOGY_RESTORE`, `PATH_QUERY`, `FAULT_DIAGNOSIS`.

## Pipeline Graph
```
START
  └─► decompose_node          — LLM: extract task_type, target_node, context
        └─► discovery_node    — HTTP: issue CLI commands, store raw outputs
              └─► parse_node  — LLM (ParserAgent): normalize raw CLI → structured JSON
                    └─► compute_node — pure Python: graph/routing/fault computation
                          └─► reasoning_node    — LLM: interpret facts → answer
                                └─► format_node
                                      ├─► [valid]   → END
                                      └─► [invalid, retry < 2] → reasoning_node
                                      └─► [incomplete facts] → discovery_node
```

## Nodes

| Node | LLM? | Description |
|------|------|-------------|
| `decompose_node` | **Yes** (small) | Classifies task type, extracts target node and candidate nodes from question |
| `discovery_node` | No | Issues CLI commands to Track B API; stores raw `(output, vendor, command_type)` in `tool_cache` only |
| `parse_node` | **Yes** (ParserAgent) | Passes each cached raw output through `ParserAgent` with `VENDOR_PARSER_SKILL`; populates structured facts |
| `compute_node` | No | Calls `build_topology_graph`, `trace_path`, `detect_faults`, `reconcile_arp_vs_lldp` |
| `reasoning_node` | **Yes** | Receives structured facts only; produces final answer |
| `format_validation_node` | No | Strict regex per task type; triggers retry if format invalid |

## Discovery Strategy per Task Type

| Task Type | Commands Issued |
|-----------|----------------|
| `TOPOLOGY_RESTORE` | LLDP on all candidate nodes; ARP fallback for nodes with empty LLDP |
| `PATH_QUERY` | `display ip routing-table` on source; hop-by-hop `display ip interface brief` |
| `FAULT_DIAGNOSIS` | `display interface brief` → `display ip routing-table` → `display current-configuration` on faulty node |

## Separation: discovery_node vs parse_node
`discovery_node` is now **pure HTTP** — it only calls the CLI API and stores raw text in `tool_cache`. It never calls the LLM. `parse_node` is **pure parsing** — it iterates over `tool_cache` entries and calls `ParserAgent` for each one. This separation means:
- On retry, `parse_node` can re-run with a corrected skill without making new API calls.
- API budget is tracked only in `discovery_node`, never accidentally consumed by retries.

## Budget Guard
`discovery_node` checks `state["budget_used"] < budget_limit` before each call. Uses `tool_cache` to avoid re-querying. `parse_node` has no budget cost (no API calls).

## LLM
Same `get_llm()` factory as `agents_track_a` — dev/prod switch via `ENV`.

The `parse_node` uses a **separate, smaller LLM instance** if available (e.g. `qwen3:1.7b` in dev). Parsing is a structured extraction task that does not require the full model capacity. In prod, it uses the same Qwen3.5-35B-A3B but with `temperature=0` and `max_tokens` capped low.

## Dependencies
- `langgraph`, `langchain_ollama`, `langchain_openai`, `state`, `tools.parsers_track_b`, `tools.compute_track_b`, `prompts.code6_prompts`
