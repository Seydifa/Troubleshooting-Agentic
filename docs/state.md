# state — Shared Pipeline State

**Source:** `src/state.py`

## Purpose
Defines the typed state objects passed between all LangGraph nodes. Acts as the single contract across the full multi-agent pipeline.

## Key Types

| Type | Track | Description |
|------|-------|-------------|
| `TrackType` | Both | Enum: `A` or `B` |
| `ProblemTypeA` | A | Enum: `LATE_HANDOVER`, `INTERFERENCE`, `COVERAGE_HOLE`, `TX_POWER_ISSUE`, `PDCCH_ISSUE`, `NEIGHBOR_MISSING`, `UNKNOWN` |
| `TaskTypeB` | B | Enum: `TOPOLOGY_RESTORE`, `PATH_QUERY`, `FAULT_DIAGNOSIS`, `UNKNOWN` |
| `QuestionStateA` | A | Full state dict for one Track A question through the pipeline |
| `QuestionStateB` | B | Full state dict for one Track B question through the pipeline |

## QuestionStateA Fields
- `scenario_id`, `question`, `options`, `tag` — raw input
- `tool_cache` — keyed results from tool server (avoids duplicate API calls)
- `features` — deterministically extracted numeric/boolean features (no LLM)
- `problem_type` — classified problem category
- `rag_examples` — top-k similar training examples from RAG index
- `reasoning`, `raw_answer`, `answer` — agent output chain
- `retry_count`, `budget_used`, `error` — control flow

## QuestionStateB Fields
- `scenario_id`, `question`, `task_id` — raw input
- `task_type`, `target_node`, `extra_context` — decomposed sub-task
- `topology_facts`, `routing_facts`, `interface_facts`, `arp_facts` — parsed CLI outputs
- `computed_topology`, `computed_path`, `fault_candidates` — pure Python computation results
- `tool_cache`, `budget_used` — API call tracking
- `reasoning`, `raw_answer`, `answer` — agent output chain
- `retry_count`, `error` — control flow

## Factory Functions
- `make_initial_state_a(scenario: dict) -> QuestionStateA`
- `make_initial_state_b(scenario: dict) -> QuestionStateB`

## Dependencies
None (stdlib only).
