# rag — Tabular RAG (Feature-Vector KNN Index)

**Source:** `src/rag.py`

## Purpose
Build and query a similarity index over Track A training examples. Retrieves the top-k most similar past scenarios to use as few-shot examples in the Analysis Agent's context window (~25% of prompt budget).

## Why Feature Vectors (not text embeddings)
Text embeddings of `"RSRP -83.07 dBm"` and `"RSRP -84.2 dBm"` are nearly identical regardless of telecom significance. Feature-vector KNN on `[drop_pct, sinr, rsrp_delta, a3_threshold, pci_stable, ho_failure, ...]` retrieves genuinely similar RF scenarios.

## Feature Vector (8 dims, all normalized to ~[0,1])
```
[drop_pct, sinr/30, rsrp_delta/20, a3_threshold/10, pci_stable, ho_failure, neighbor_missing, neighbor_count/10]
```

## RAGEntry
```
scenario_id, problem_type, feature_vector, tool_summary, answer, reasoning_template
```
`to_context_block()` → formatted few-shot example string.

## TabularRAG
| Method | Description |
|--------|-------------|
| `build_from_train(train_json_path, client)` | Extracts features for each train example via tool server, fits sklearn KNN |
| `retrieve(feature_vector)` | Returns top-k `RAGEntry` objects |
| `format_context(feature_vector)` | Returns formatted few-shot context string for prompt injection |
| `save(path)` / `load(path)` | Persist/restore index to avoid rebuilding on every run |

## Index Technology
`sklearn.neighbors.NearestNeighbors` with Euclidean distance. Simple, fast, no FAISS dependency. Sufficient for 2000 training examples.

## Dependencies
- `sklearn`, `numpy`, `pickle`, `state`, `tools.tools_track_a`
