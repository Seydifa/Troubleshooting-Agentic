"""
main.py — CLI Entry Point

Startup sequence:
1. Load .env via python-dotenv
2. Detect ENV=dev|prod → select LLM
3. If --build-rag: build TabularRAG from train.json and save
4. Else: load existing RAG index from --rag-index if it exists
5. Initialise Orchestrator with all components
6. Run orchestrator.run(test_data)
7. Write result.csv

Usage:
    python src/main.py \\
      --track both \\
      --phase 1 \\
      --test-file data/test.json \\
      --output result.csv \\
      [--build-rag] \\
      [--rag-index rag_index.pkl] \\
      [--verbose]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_json(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        return data.get("data") or data.get("scenarios") or data.get("questions") or []
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Telco Troubleshooting Agentic — Competition Runner"
    )
    parser.add_argument(
        "--track",
        choices=["A", "B", "both"],
        default="both",
        help="Which track(s) to run (default: both)",
    )
    parser.add_argument(
        "--phase",
        choices=["1", "2"],
        default="1",
        help="Competition phase (affects budget limits)",
    )
    parser.add_argument(
        "--test-file",
        default=os.getenv("TEST_FILE_PATH", ""),
        help="Path to test.json (single-track runs). For --track both, use --test-file-a/--test-file-b.",
    )
    parser.add_argument(
        "--test-file-a",
        default=os.getenv(
            "TEST_FILE_A_PATH",
            "data/raw/Track A/data/Phase_1/test.json",
        ),
        help="Path to Track A test.json (used with --track both or --track A)",
    )
    parser.add_argument(
        "--test-file-b",
        default=os.getenv(
            "TEST_FILE_B_PATH",
            "data/raw/Track B/data/Phase_1/test.json",
        ),
        help="Path to Track B test.json (used with --track both or --track B)",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("OUTPUT_CSV_PATH", "result.csv"),
        help="Path for result.csv output",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the HuggingFace dataset before doing anything else",
    )
    parser.add_argument(
        "--build-rag",
        action="store_true",
        help="Rebuild the RAG index from train.json (Track A only)",
    )
    parser.add_argument(
        "--train-file",
        default="data/train.json",
        help="Path to train.json (used with --build-rag)",
    )
    parser.add_argument(
        "--rag-index",
        default="rag_index.pkl",
        help="Path to save/load the RAG index pickle",
    )
    parser.add_argument(
        "--warm-cache",
        action="store_true",
        help="Pre-fetch all Track A tool endpoints for every scenario then save to --tool-cache. Exits after warming unless --no-exit-after-warm is passed.",
    )
    parser.add_argument(
        "--no-exit-after-warm",
        action="store_true",
        help="Continue to inference after --warm-cache instead of exiting",
    )
    parser.add_argument(
        "--tool-cache",
        default=os.getenv("TOOL_CACHE_PATH", ""),
        help="Path to a pre-warmed tool cache pickle (load before inference, save after --warm-cache)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N scenarios (for quick testing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # ------------------------------------------------------------------
    # Load environment
    # .env always wins — override=True prevents notebook/shell env vars
    # (e.g. MODEL_NAME exported from a Jupyter cell) from bleeding in.
    # ------------------------------------------------------------------
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except ImportError:
        logger.warning("python-dotenv not installed; skipping .env load")

    # Flush any LLM singletons that may have been created with stale env vars
    try:
        from src.llm import clear_llm_cache
        clear_llm_cache()
    except Exception:
        pass

    env = os.getenv("ENV", "dev")
    logger.info("Environment: %s", env)

    # ------------------------------------------------------------------
    # Optional: download dataset from HuggingFace
    # ------------------------------------------------------------------
    if args.download:
        logger.info("Downloading dataset from HuggingFace …")
        from src.download import download as hf_download

        hf_download()

    # ------------------------------------------------------------------
    # Load test data
    # ------------------------------------------------------------------
    test_data: list = []

    if args.track == "A":
        path_a = args.test_file or args.test_file_a
        logger.info("Loading Track A data from %s", path_a)
        scenarios = _load_json(path_a)
        for s in scenarios:
            s["track"] = "A"
        test_data = scenarios

    elif args.track == "B":
        path_b = args.test_file or args.test_file_b
        logger.info("Loading Track B data from %s", path_b)
        scenarios = _load_json(path_b)
        for s in scenarios:
            s["track"] = "B"
        test_data = scenarios

    else:  # both
        logger.info("Loading Track A data from %s", args.test_file_a)
        for s in _load_json(args.test_file_a):
            s["track"] = "A"
            test_data.append(s)
        logger.info("Loading Track B data from %s", args.test_file_b)
        for s in _load_json(args.test_file_b):
            s["track"] = "B"
            test_data.append(s)

    logger.info("Loaded %d scenarios total (track=%s)", len(test_data), args.track)

    if args.limit is not None:
        test_data = test_data[: args.limit]
        logger.info("Limiting to first %d scenarios", args.limit)

    # ------------------------------------------------------------------
    # Initialise Track A components
    # ------------------------------------------------------------------
    from src.tools.tools_track_a import TrackAClient
    from src.rag import TabularRAG

    tool_server_url = os.getenv("TOOL_SERVER_URL", "http://localhost:8000")
    client_a = TrackAClient(base_url=tool_server_url)

    # ------------------------------------------------------------------
    # Tool cache: load pre-warmed cache, or warm it now
    # ------------------------------------------------------------------
    if args.tool_cache and Path(args.tool_cache).exists():
        logger.info("Loading tool cache from %s …", args.tool_cache)
        client_a.load_cache(args.tool_cache)

    if args.warm_cache:
        track_a_ids = [
            s["scenario_id"]
            for s in test_data
            if s.get("track") == "A" and s.get("scenario_id")
        ]
        logger.info("Warming cache for %d Track A scenarios …", len(track_a_ids))
        client_a.warm_all(track_a_ids)
        cache_path = args.tool_cache or "tool_cache_a.pkl"
        client_a.save_cache(cache_path)
        logger.info("Tool cache saved to %s", cache_path)
        if not args.no_exit_after_warm:
            logger.info(
                "--warm-cache done. Re-run without --warm-cache to run inference."
            )
            return

    rag = TabularRAG(k=3)
    if args.build_rag:
        logger.info("Building RAG index from %s …", args.train_file)
        rag.build_from_train(args.train_file, client_a)
        rag.save(args.rag_index)
        logger.info("RAG index saved to %s", args.rag_index)
    elif Path(args.rag_index).exists():
        logger.info("Loading RAG index from %s", args.rag_index)
        rag.load(args.rag_index)
    else:
        logger.warning(
            "RAG index not found at %s — Track A will run without few-shot examples",
            args.rag_index,
        )

    # ------------------------------------------------------------------
    # Initialise Track B components
    # ------------------------------------------------------------------
    from src.tools.parsers_track_b import TrackBClient

    track_b_url = os.getenv("TOOL_SERVER_URL", "http://localhost:8000")
    daily_limit = 1000 if args.phase == "1" else 2000
    client_b = TrackBClient(base_url=track_b_url, daily_limit=daily_limit)

    # ------------------------------------------------------------------
    # Build LangGraph pipelines
    # ------------------------------------------------------------------
    from src.agents.agents_track_a import build_graph_a
    from src.agents.agents_track_b import build_graph_b

    logger.info("Compiling LangGraph pipelines …")
    graph_a = build_graph_a(client=client_a, rag=rag)
    graph_b = build_graph_b(client=client_b)

    # ------------------------------------------------------------------
    # Orchestrate
    # ------------------------------------------------------------------
    from src.orchestrator import Orchestrator

    orc = Orchestrator(
        {
            "track_a_graph": graph_a,
            "track_b_graph": graph_b,
            "track_b_client": client_b,
            "daily_limit": daily_limit,
        }
    )

    logger.info("Starting run …")
    results = orc.run(test_data)

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    Orchestrator.write_csv(results, args.output)
    logger.info("Done. Results written to %s", args.output)


if __name__ == "__main__":
    main()
