# Architecture Overview — Telco Troubleshooting Agentic Challenge

## 1. Design Philosophy

The core principle of this architecture is **separation of computation from reasoning**:

> The LLM is responsible for *understanding* and *deciding*. It is never responsible for *computing*.

All arithmetic, graph traversal, threshold comparisons, regex parsing, and format validation are handled by pure Python tools. The LLM only receives clean, structured facts and maps them to an answer. This directly reduces hallucination on numerical operations — the single most common failure mode in telecom fault diagnosis tasks.

A secondary principle is **reasoning contamination isolation**: instead of a single agent accumulating a long, polluted context across many tool calls, the pipeline is split into focused nodes where each agent starts with a clean, minimal context. Early wrong intermediate conclusions cannot silently bias later reasoning steps.

---

## 2. High-Level System Map

```
                          ┌─────────────────────────────┐
                          │          main.py             │
                          │  CLI entry point, env setup  │
                          └──────────────┬───────────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │         orchestrator.py       │
                          │  route by track, concurrency  │
                          │  budget tracking, result.csv  │
                          └───────────┬──────────┬────────┘
                                      │          │
               ┌──────────────────────▼──┐   ┌───▼──────────────────────┐
               │   agents/agents_track_a │   │  agents/agents_track_b   │
               │   LangGraph StateGraph  │   │  LangGraph StateGraph     │
               └──────────┬─────────────┘   └──────────────┬────────────┘
                          │                                 │
         ┌────────────────┴──────────┐     ┌───────────────┴──────────────┐
         │    tools/tools_track_a    │     │   tools/parsers_track_b      │
         │  HTTP client + math tools │     │   vendor-aware CLI parsers   │
         └───────────────────────────┘     └──────────────────────────────┘
                                                           │
                                           ┌───────────────▼──────────────┐
                                           │   tools/compute_track_b      │
                                           │  graph, routing, fault logic  │
                                           └──────────────────────────────┘
         ┌───────────────────────────┐
         │         rag.py            │
         │  KNN feature-vector index │  (Track A only)
         └───────────────────────────┘
         ┌───────────────────────────┐
         │    prompts/code6_prompts  │
         │  system prompts + skills  │
         └───────────────────────────┘
         ┌───────────────────────────┐
         │         state.py          │
         │  typed state contracts    │  (shared by all modules)
         └───────────────────────────┘
```

---

## 3. Module Inventory

| File | Layer | LLM? | Description |
|------|-------|------|-------------|
| `src/main.py` | Entry point | No | CLI args, env loading, startup sequence |
| `src/orchestrator.py` | Routing | No | Track dispatch, concurrency, budget, CSV writer |
| `src/state.py` | Contract | No | Typed state dicts for both tracks + enums |
| `src/rag.py` | Retrieval | No | Feature-vector KNN index on Track A train data |
| `src/prompts/code6_prompts.py` | Prompts | No | All system prompts, skill context, `VENDOR_PARSER_SKILL` |
| `src/agents/agents_track_a.py` | Pipeline | **Yes** | LangGraph graph for Track A |
| `src/agents/agents_track_b.py` | Pipeline | **Yes** | LangGraph graph for Track B |
| `src/tools/tools_track_a.py` | Tools | No | HTTP client + deterministic feature extractors |
| `src/tools/parsers_track_b.py` | Tools | **Yes** (ParserAgent) | `VendorContextBuilder` + `ParserAgent` + `SchemaValidator` |
| `src/tools/compute_track_b.py` | Tools | No | Graph, routing, reconciliation, fault detection |

---

## 4. Track A Pipeline — Wireless (5G) Troubleshooting

### 4.1 Overview

Track A questions present a 5G drive test scenario and ask the agent to select the correct optimisation action(s) from a list of candidates (C1…Cn). The answer is either a single option (`C8`) or multiple (`C5|C9|C11`) sorted in ascending order.

### 4.2 LangGraph Pipeline

```
START
  │
  ▼
[retrieval_node]              ← NO LLM
  Calls ALL Tool Server endpoints upfront for the scenario:
  throughput_logs, serving_cell_pci, cell_info, serving_rsrp,
  serving_sinr, neighboring_cells_pci, neighboring_cell_rsrp,
  user_location. Populates state["tool_cache"].
  │
  ▼
[feature_extraction_node]     ← NO LLM
  Pure Python math on tool_cache:
  • parse_throughput_series()  → drop_pct, degradation_timestamp
  • compute_a3_threshold_db()  → threshold in dB (unit: 0.5dB slots)
  • detect_handover_failure()  → delta_db, threshold_db, ho_failure bool
  • classify_problem_type()    → LATE_HANDOVER | INTERFERENCE | ...
  • build_feature_vector()     → [8 floats] for RAG KNN query
  Populates state["features"] and state["problem_type"].
  │
  ▼
[rag_retrieval_node]          ← NO LLM
  Queries TabularRAG KNN index with feature vector.
  Returns top-3 similar training examples as few-shot context strings.
  Populates state["rag_examples"].
  │
  ▼
[analysis_node]               ← LLM (single call)
  Context window budget:
    ~25% → system prompt (TRACK_A_ANALYSIS_SYSTEM) + TRACK_A_SKILL
    ~40% → structured feature dict (never raw CSV/JSON)
    ~25% → RAG few-shot examples (top-3)
    ~10% → options list + chain-of-thought output
  Produces state["raw_answer"].
  │
  ▼
[validation_node]             ← NO LLM
  Checks:
  • Format: C\d+(\|C\d+)*
  • Ascending order
  • Count matches tag (single-answer → exactly 1, multiple-answer → 2–4)
  │
  ├─► [valid]   → END  →  state["answer"]
  └─► [invalid, retry_count < 2]  → analysis_node  (with error feedback)
```

### 4.3 Key Design Decisions

**All tool calls upfront** — `retrieval_node` fetches everything in one pass. On retry, no additional API calls are made because `tool_cache` already holds all results.

**LLM never does arithmetic** — `IntraFreqHoA3Offset [0.5dB]: 10` is converted to `5.0 dB` by `compute_a3_threshold_db()` before the LLM sees it. The LLM only reads `"a3_threshold_db": 5.0, "rsrp_delta_db": 6.0, "handover_failure": true"`.

**RAG uses feature vectors, not text embeddings** — Two scenarios with `RSRP -83 dBm` and `RSRP -84 dBm` are textually almost identical but physically equivalent. KNN on `[drop_pct, sinr, rsrp_delta, a3_threshold, pci_stable, ...]` retrieves scenarios with genuinely similar RF conditions.

---

## 5. Track B Pipeline — IP Network Troubleshooting

### 5.1 Overview

Track B questions require the agent to interact with a simulated multi-vendor CLI (Huawei / Cisco / H3C) to answer open-ended questions about network topology, routing paths, and fault diagnosis. Answers are free-form text with strict formatting rules.

Three task types:
- **TOPOLOGY_RESTORE** — list all UP links of a target node: `Node(Port)->Node(Port)` per line
- **PATH_QUERY** — routing path between two nodes: `NodeA->NodeB->NodeC`
- **FAULT_DIAGNOSIS** — root cause: `node;port/prefix;cause`

### 5.2 LangGraph Pipeline

```
START
  │
  ▼
[decompose_node]              ← LLM (small, structured output)
  Reads the question and extracts:
  • task_type: TOPOLOGY_RESTORE | PATH_QUERY | FAULT_DIAGNOSIS
  • target_node: the primary node to investigate
  • extra_context: {candidate_nodes, destination_ip, faulty_node, ...}
  Output is a JSON dict — small, deterministic, no chain-of-thought needed.
  │
  ▼
[discovery_node]              ← NO LLM — pure HTTP only
  Issues CLI commands via TrackBClient (POST /api/agent/execute).
  Stores raw (output, vendor, command_type) in tool_cache ONLY.
  Does NOT parse. Budget guard: checks budget_used < 1000 before each call.

  TOPOLOGY_RESTORE:
    → display lldp neighbor on each candidate node
    → display arp + interface brief as fallback
  PATH_QUERY:
    → display ip routing-table on source node
    → display ip interface brief on each next-hop device
  FAULT_DIAGNOSIS:
    → display interface brief → display ip routing-table
      → display current-configuration on faulty node
  │
  ▼
[parse_node]                  ← LLM — ParserAgent (small, JSON-only output)
  Iterates tool_cache. For each raw entry calls ParserAgent:
    1. VendorContextBuilder selects the matching VENDOR_PARSER_SKILL section
       for the (vendor, command_type) pair — no full-skill injection.
    2. ParserAgent (temperature=0) extracts structured JSON.
    3. SchemaValidator checks output; retries once with error feedback if invalid.
    4. _normalize_port() canonicalizes all port names.
  Populates state["topology_facts"], ["routing_facts"], ["interface_facts"], ["arp_facts"].
  No API calls — no budget cost. Safe to retry independently of discovery.
  │
  ▼
[compute_node]                ← NO LLM
  Pure Python computation on parsed facts:
  • build_topology_graph()      → adjacency dict from topology_facts
  • find_links_for_node()       → reverse lookups for unqueryable nodes
  • reconcile_arp_vs_lldp()     → ARP port overrides LLDP when they differ
  • trace_path()                → hop-by-hop via longest-prefix match
  • detect_faults()             → admin-down ports + blackhole routes
  Populates computed_topology, computed_path, fault_candidates.
  │
  ▼
[reasoning_node]              ← LLM (single call)
  Context window budget:
    ~25% → system prompt (TRACK_B_REASONING_SYSTEM) + TRACK_B_SKILLS
    ~65% → structured facts (topology/routing/interface/fault dicts)
    ~10% → question + format requirements + output
  Receives ONLY structured facts — never raw CLI output.
  Produces state["raw_answer"].
  │
  ▼
[format_validation_node]      ← NO LLM
  Per task type regex validation:
  TOPOLOGY:  ^[A-Za-z0-9\-]+\([A-Za-z0-9\/]+\)->[A-Za-z0-9\-]+\([A-Za-z0-9\/]+\)$  (per line)
  PATH:      single line, NodeA->NodeB->...  no extra whitespace
  FAULT:     node;port_or_prefix;cause  semicolon-separated
  │
  ├─► [valid]                        → END → state["answer"]
  ├─► [invalid, retry_count < 2]     → reasoning_node
  └─► [empty facts, retry_count < 2] → discovery_node (broader search)
```

### 5.3 Key Design Decisions

**Parser is now LLM-powered — not brittle regex** — `parsers_track_b.py` contains a `ParserAgent` that uses the `VENDOR_PARSER_SKILL` to normalize any vendor CLI output into a canonical schema. The LLM is good at reading semi-structured text and extracting structured data; it handles vendor firmware variations, unexpected error lines, and edge cases that regex cannot. The vendor is always provided by the API response field `"vendor"`, so identification is free.

**`VENDOR_PARSER_SKILL` is the centralized vendor knowledge base** — all vendor-specific format knowledge lives in one place in `prompts.py`. Each `(vendor, command_type)` pair has its own section. Adding support for a new vendor means adding one section to the skill — no new parser function, no new regex.

**Skill injection is scoped, not full** — `VendorContextBuilder` selects only the relevant skill section for the current call. The `ParserAgent` never sees the entire skill, keeping its prompt budget minimal (fast + cheap).

**discovery_node and parse_node are decoupled** — `discovery_node` is pure HTTP (API calls only). `parse_node` is pure LLM (no API calls). This means on retry, parsing can be re-run without consuming any API budget. It also means the two concerns can be independently optimized or replaced.

**LLM never traverses graphs** — `trace_path()` in `compute_track_b.py` uses IP longest-prefix match and ARP resolution to produce `["NodeA", "NodeB", "NodeC"]`. The reasoning agent only reads `"path: NodeA → NodeB → NodeC"` and formats it.

**ARP overrides LLDP** — per competition rules, when interface description (LLDP) and ARP table port info conflict, ARP takes precedence. `reconcile_arp_vs_lldp()` enforces this deterministically.

---

## 6. Shared Components

### 6.1 state.py — Pipeline Contract

Defines `QuestionStateA` and `QuestionStateB` as typed dicts. Every LangGraph node reads from and writes to this shared state. The state is the only coupling between nodes — no node imports another node directly.

### 6.2 rag.py — Tabular RAG (Track A only)

Built offline from `train.json` (2000 labelled examples). Each example is reduced to an 8-dimensional feature vector. At query time, KNN (sklearn `NearestNeighbors`, Euclidean) retrieves the top-3 most similar scenarios. These are formatted as few-shot examples and injected into the analysis agent's context.

The index is saved to disk (`rag_index.pkl`) after the first build and loaded on subsequent runs to avoid re-processing 2000 scenarios.

Track B has no labelled training set, so RAG is not used. The `TRACK_B_SKILLS` prompt and discovered `traces.json` examples serve as the few-shot foundation instead.

### 6.3 prompts/code6_prompts.py — Context Budget

The 25% system prompt budget is fixed across all runs and contains:
- **Skill context**: telecom domain rules (A3 formula, RSRP thresholds, LLDP priority, fault taxonomy)
- **Role definition**: agent persona (RF engineer / IP network engineer)
- **Output format**: exact format constraints repeated in the system prompt as a hard rule

The remaining 75% is variable: structured facts + RAG examples + CoT output.

**`VENDOR_PARSER_SKILL`** is a separate skill used exclusively by the `ParserAgent`. It is never injected into the reasoning agents — it is scoped to the parsing layer only. Its budget cost is minimal because only the relevant `(vendor, command_type)` section is injected per call, not the full skill.

---

## 7. Orchestrator

`orchestrator.py` is the only module that knows about both tracks simultaneously.

Responsibilities:
- Load `test.json`, split questions by track
- Run Track A questions sequentially (no concurrency limit noted)
- Run Track B questions with `ThreadPoolExecutor(max_workers=2)` — enforces the competition's "max 2 concurrent problems" rule
- Track global `budget_used` counter across all Track B questions (Phase 1 limit: 1000/day)
- Merge Track A and Track B answers by `scenario_id` into a single DataFrame
- Write `result.csv` with columns `ID, Track A, Track B`

---

## 8. Dev / Prod Switch

All LLM calls go through a single factory function `get_llm()` in both agent files:

```python
# ENV=dev  → Ollama local, fast iteration
ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL)

# ENV=prod → OpenRouter, competition model
ChatOpenAI(model="Qwen/Qwen3.5-35B-A3B", base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)
```

No other code changes between dev and prod. The `.env` file is the only switch.

---

## 9. Data Flow Summary

```
test.json
    │
    ▼ orchestrator.py
    │   route by track
    │
    ├─── Track A ──────────────────────────────────────────────────────────►
    │   retrieval_node (HTTP) → feature_extraction_node (Python math)
    │   → rag_node (KNN lookup) → analysis_node (LLM) → validate_node
    │                                                         │
    │                                                    answer string
    │
    └─── Track B ──────────────────────────────────────────────────────────►
        decompose_node (LLM)
        → discovery_node (HTTP only, raw text stored)
        → parse_node (ParserAgent + VENDOR_PARSER_SKILL → structured JSON)
        → compute_node (Python: graph/routing/fault)
        → reasoning_node (LLM) → format_validation_node
                                          │
                                     answer string
    │
    ▼ orchestrator.py
result.csv  (ID, Track A, Track B)
```

---

## 10. Dependency Graph

```
main.py
  └── orchestrator.py
        ├── state.py
        ├── rag.py
        │     └── tools/tools_track_a.py
        │               └── state.py
        ├── agents/agents_track_a.py
        │     ├── state.py
        │     ├── tools/tools_track_a.py
        │     ├── rag.py
        │     └── prompts/code6_prompts.py
        └── agents/agents_track_b.py
              ├── state.py
              ├── tools/parsers_track_b.py
              │         ├── state.py
              │         └── prompts/code6_prompts.py  (VENDOR_PARSER_SKILL)
              ├── tools/compute_track_b.py
              │         └── tools/parsers_track_b.py
              └── prompts/code6_prompts.py
```

`state.py` has no dependencies — it is the base of the entire dependency tree.
