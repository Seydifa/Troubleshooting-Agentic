# agents_track_a — Track A LangGraph Pipeline

**Source:** `src/agents/agents_track_a.py`

## Purpose
LangGraph `StateGraph` implementing the full Track A pipeline. Each node has a single responsibility; no node does both tool calls and reasoning.

## Pipeline Graph
```
START
  └─► retrieval_node        — calls tool server, populates tool_cache
        └─► feature_node    — pure Python: extract features, classify problem
              └─► rag_node  — KNN lookup, populates rag_examples
                    └─► analysis_node   — LLM: chain-of-thought → raw_answer
                          └─► validate_node
                                ├─► [valid]   → END
                                └─► [invalid, retry < 2] → analysis_node
```

## Nodes

| Node | LLM? | Description |
|------|------|-------------|
| `retrieval_node` | No | Calls tool server endpoints systematically for the scenario |
| `feature_extraction_node` | No | Calls `parse_throughput_series`, `detect_handover_failure`, `classify_problem_type`, `build_feature_vector` |
| `rag_retrieval_node` | No | Calls `TabularRAG.format_context()` with feature vector |
| `analysis_node` | **Yes** | Single LLM call with system prompt + features + RAG + options |
| `validation_node` | No | Regex validation + ascending order check + tag count check |

## Key Design Decisions
- `retrieval_node` runs ALL tool calls upfront, even ones not needed — avoids multi-turn tool calling overhead
- `analysis_node` receives ONLY the structured feature dict, never raw CSV/JSON from tools
- `validation_node` forces retry (up to 2) if answer format is invalid
- `tool_cache` on state prevents duplicate HTTP calls on retry

## LLM
Uses `ChatOllama` in dev (`ENV=dev`) and `ChatOpenAI` with OpenRouter in prod (`ENV=prod`). Model is swapped transparently via factory function `get_llm()`.

## Dependencies
- `langgraph`, `langchain_ollama`, `langchain_openai`, `state`, `tools.tools_track_a`, `rag`, `prompts.code6_prompts`
