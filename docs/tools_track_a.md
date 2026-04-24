# tools_track_a — Track A HTTP Client + Feature Extractors

**Source:** `src/tools/tools_track_a.py`

## Purpose
Two responsibilities, zero LLM:
1. `TrackAClient` — cached HTTP wrapper for all Track A Agent Tool Server endpoints.
2. Feature extractor functions — deterministic Python math that converts raw API responses into structured, numeric features the Analysis Agent can interpret without doing arithmetic itself.

## TrackAClient
Wraps all endpoints from `main.py`'s `endpoint_mapper`. Caches every response by `md5(endpoint + scenario_id + params)` to avoid duplicate API calls.

Key methods: `throughput_logs()`, `cell_info()`, `serving_pci()`, `serving_rsrp()`, `serving_sinr()`, `neighboring_pcis()`, `neighboring_rsrp()`, `user_location()`.

## Feature Extractor Functions (pure Python)

| Function | Input | Output |
|----------|-------|--------|
| `parse_throughput_series(df)` | Throughput DataFrame | min/max/avg Mbps, drop_pct, degradation_timestamp |
| `compute_a3_threshold_db(offset, hyst)` | Raw 0.5dB-unit values | Total threshold in dB |
| `detect_handover_failure(serving_rsrp, neighbor_rsrp, offset, hyst)` | RF values | delta_db, threshold_db, handover_failure bool, gap_db |
| `classify_problem_type(features)` | Feature dict | `ProblemTypeA` string |
| `build_feature_vector(features)` | Feature dict | `list[float]` for KNN RAG |

## Design Rule
**No LLM calls.** All math is done here. The Analysis Agent only sees the computed dict — never raw CSV or raw JSON from tools.

## Dependencies
- `requests`, `pandas`, `state`
