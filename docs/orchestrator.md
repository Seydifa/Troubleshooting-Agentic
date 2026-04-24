# orchestrator — Main Orchestrator

**Source:** `src/orchestrator.py`

## Purpose
Routes questions by track, manages concurrency (Track B: max 2 parallel), enforces API budget, collects answers, writes `result.csv`.

## Class: Orchestrator

### Constructor
```python
Orchestrator(config: dict)
```
Initialises both track graphs, RAG index, and clients from config.

### Key Methods

| Method | Description |
|--------|-------------|
| `run(test_data)` | Process all scenarios; returns `[{"ID": ..., "Track A": ..., "Track B": ...}]` |
| `run_question_a(scenario)` | Run Track A graph for one scenario |
| `run_question_b(scenario)` | Run Track B graph for one scenario |
| `write_csv(results, output_path)` | Write competition `result.csv` |

## Concurrency
Track B: `ThreadPoolExecutor(max_workers=2)` — respects the "max 2 concurrent" rule from the competition.
Track A: processes sequentially (no concurrency restriction noted, but can be parallelised).

## Budget Tracking
Global `budget_used` counter shared across all Track B questions. Orchestrator halts new Track B calls when `budget_used >= daily_limit` (default 1000).

## Result Merging
Both tracks share the same `scenario_id` as the row `ID`. The orchestrator merges Track A and Track B answers into a single DataFrame before writing.

## Dependencies
- `concurrent.futures`, `csv`, `state`, `agents.agents_track_a`, `agents.agents_track_b`, `rag`, `tools.tools_track_a`, `tools.parsers_track_b`
