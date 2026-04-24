# Troubleshooting-Agentic

LangGraph-based agentic system for the **Telco Troubleshooting Agentic Challenge**.

## Tracks

| Track | Domain | Server | Model |
|-------|--------|--------|-------|
| A | 5G RF / drive-test troubleshooting | FastAPI (port 8000) | `qwen3.5:0.8b` via Ollama |
| B | IP network topology / path / fault diagnosis | Flask (port 8000) | `qwen3.5:0.8b` via Ollama |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in secrets
cp .env.example .env   # set HF_TOKEN, OLLAMA_BASE_URL, etc.

# 3. Download dataset (gated — accept terms first)
python src/download.py

# 4. Pull the local model
ollama pull qwen3.5:0.8b

# 5. Start the Track A tool server (separate terminal)
cd "data/raw/Track A"
uvicorn server:app --host 0.0.0.0 --port 8000

# 6. Pre-warm tool cache (optional but fast inference)
PYTHONPATH=. python src/main.py --track A --warm-cache --tool-cache tool_cache_a.pkl

# 7. Run evaluation
PYTHONPATH=. python src/main.py --track A --tool-cache tool_cache_a.pkl
# or with a quick smoke test
PYTHONPATH=. python src/main.py --track A --limit 3 --verbose
```

## CLI Reference

| Flag | Description |
|------|-------------|
| `--track A\|B\|both` | Which track(s) to run (default: `both`) |
| `--limit N` | Process only the first N scenarios (dev testing) |
| `--download` | Download dataset from HuggingFace before running |
| `--warm-cache` | Pre-fetch all Track A tool endpoints and save to `--tool-cache` |
| `--tool-cache PATH` | Load / save pre-warmed tool response cache (pickle) |
| `--no-exit-after-warm` | Continue to inference after `--warm-cache` |
| `--build-rag` | Rebuild TabularRAG index from `train.json` |
| `--rag-index PATH` | Path for RAG index pickle (default: `rag_index.pkl`) |
| `--verbose` | Enable DEBUG logging |

## Tests

```bash
python -m pytest tests/ -v
```

All 181 tests pass.
