# main — Entry Point

**Source:** `src/main.py`

## Purpose
CLI entry point. Loads environment, initialises components, runs orchestrator, writes output.

## Arguments
```
python src/main.py
  --track          A | B | both   (default: both)
  --phase          1 | 2          (default: 1)
  --test-file      path to test.json
  --output         path to result.csv
  --build-rag      flag: rebuild RAG index from train.json (Track A only)
  --rag-index      path to saved RAG index file
  --verbose        flag: enable debug logging
```

## Startup Sequence
1. Load `.env` via `python-dotenv`
2. Detect `ENV=dev` or `ENV=prod` → select LLM
3. If `--build-rag`: build TabularRAG from `train.json` using TrackAClient, save to `--rag-index`
4. Else: load RAG from `--rag-index` if exists
5. Initialise `Orchestrator` with all components
6. Run `orchestrator.run(test_data)`
7. Write `result.csv`

## Environment Variables Used
From `.env`:
- `ENV`, `MODEL_NAME`, `OLLAMA_BASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`
- `TOOL_SERVER_URL` (Track A), `HF_TOKEN`
- `TEST_FILE_PATH`, `OUTPUT_CSV_PATH`

## Dependencies
- `argparse`, `dotenv`, `logging`, `orchestrator`
