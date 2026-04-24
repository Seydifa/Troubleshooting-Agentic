"""
orchestrator.py — Main Orchestrator

Routes questions by track, manages concurrency (Track B: max 2 parallel),
enforces API budget, collects answers, writes result.csv.

Dependencies: concurrent.futures, csv, state,
              agents.agents_track_a, agents.agents_track_b,
              rag, tools.tools_track_a, tools.parsers_track_b
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.state import (
    QuestionStateA,
    QuestionStateB,
    TrackType,
    make_initial_state_a,
    make_initial_state_b,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Routes questions by track and manages the full run lifecycle.

    Parameters
    ----------
    config : dict
        Required keys:
        - track_a_graph        : compiled LangGraph for Track A
        - track_b_graph        : compiled LangGraph for Track B
        - track_b_client       : TrackBClient (for budget_used synchronisation)
        - daily_limit (int)    : Track B API budget limit (default 1000)
    """

    def __init__(self, config: Dict[str, Any]):
        self._graph_a = config["track_a_graph"]
        self._graph_b = config["track_b_graph"]
        self._client_b = config["track_b_client"]
        self._daily_limit = int(config.get("daily_limit", 1000))
        self._budget_lock = threading.Lock()
        self._budget_used = 0
        # Optional W&B logger — pass wandb_logger=WandbLogger(...) in config
        self._wandb_logger = config.get("wandb_logger")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _process_track(self, scenarios: List[Dict[str, Any]], run_fn, max_workers: int, track_name: str, results_dict: Dict[str, str], log_method_name: str) -> None:
        if not scenarios:
            return
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_fn, scenario): scenario.get("scenario_id", "")
                for scenario in scenarios
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    res = future.result()
                    answer = res[1]
                    results_dict[sid] = answer
                    if self._wandb_logger is not None:
                        log_fn = getattr(self._wandb_logger, log_method_name)
                        log_fn(*res)
                except Exception as exc:
                    logger.error("%s scenario %s failed: %s", track_name, sid, exc)
                    results_dict[sid] = ""

    def run(self, test_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process all scenarios and return merged result rows.

        Parameters
        ----------
        test_data : list[dict]
            Parsed contents of test.json. Each entry should have a
            ``"scenario_id"`` and a ``"track"`` field (``"A"`` or ``"B"``).

        Returns
        -------
        list[dict]
            Rows like ``{"ID": str, "Track A": str, "Track B": str}``.
        """
        track_a_scenarios = [s for s in test_data if s.get("track") == "A"]
        track_b_scenarios = [s for s in test_data if s.get("track") == "B"]

        results_a: Dict[str, str] = {}
        results_b: Dict[str, str] = {}

        # Run both tracks concurrently using threads to optimize for run time
        t_a = threading.Thread(
            target=self._process_track,
            args=(track_a_scenarios, self._run_question_a, 4, "Track A", results_a, "log_track_a")
        )
        t_b = threading.Thread(
            target=self._process_track,
            args=(track_b_scenarios, self._run_question_b, 2, "Track B", results_b, "log_track_b")
        )
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

        # Merge by scenario_id
        all_ids = sorted(set(list(results_a.keys()) + list(results_b.keys())))
        merged: List[Dict[str, str]] = []
        for sid in all_ids:
            merged.append(
                {
                    "ID": sid,
                    "Track A": results_a.get(sid, ""),
                    "Track B": results_b.get(sid, ""),
                }
            )
        return merged

    def run_question_a(self, scenario: Dict[str, Any]) -> str:
        """Public wrapper: run Track A for one scenario, return answer string."""
        _, answer, *_ = self._run_question_a(scenario)
        return answer

    def run_question_b(self, scenario: Dict[str, Any]) -> str:
        """Public wrapper: run Track B for one scenario, return answer string."""
        _, answer, *_ = self._run_question_b(scenario)
        return answer

    @staticmethod
    def write_csv(results: List[Dict[str, str]], output_path: str) -> None:
        """Write the competition result.csv.

        Parameters
        ----------
        results : list[dict]
            Rows with keys ``ID, Track A, Track B``.
        output_path : str
            Destination file path.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ID", "Track A", "Track B"])
            writer.writeheader()
            writer.writerows(results)
        logger.info("result.csv written to %s (%d rows)", output_path, len(results))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_question_a(
        self, scenario: Dict[str, Any]
    ) -> tuple[str, str, Dict[str, Any], float, str]:
        """Run the Track A LangGraph for one scenario.

        Returns (scenario_id, answer, final_state, elapsed_s, status).
        """
        sid = scenario.get("scenario_id", "")
        logger.info("[Track A] Processing %s", sid)
        final_state: Dict[str, Any] = {}
        status = "ok"
        t0 = time.perf_counter()
        try:
            initial_state = make_initial_state_a(scenario)
            final_state = self._graph_a.invoke(initial_state)
            answer = final_state.get("answer") or final_state.get("raw_answer", "")
            if not answer:
                status = "empty"
        except Exception as exc:
            logger.error("[Track A] Error on %s: %s", sid, exc)
            answer = ""
            status = "error"
        elapsed = time.perf_counter() - t0
        logger.info(
            "[Track A] %s → %s  (%.1fs, status=%s)", sid, answer, elapsed, status
        )
        return sid, answer, final_state, elapsed, status

    def _run_question_b(self, scenario: Dict[str, Any]) -> tuple[str, str, float, str]:
        """Run the Track B LangGraph for one scenario (thread-safe budget check).

        Returns (scenario_id, answer, elapsed_s, status).
        """
        sid = scenario.get("scenario_id", "")
        with self._budget_lock:
            if self._budget_used >= self._daily_limit:
                logger.warning(
                    "[Track B] Budget exhausted (%d/%d) — skipping %s",
                    self._budget_used,
                    self._daily_limit,
                    sid,
                )
                return sid, "", 0.0, "skipped"

        logger.info("[Track B] Processing %s", sid)
        status = "ok"
        t0 = time.perf_counter()
        try:
            initial_state = make_initial_state_b(scenario)
            final_state: QuestionStateB = self._graph_b.invoke(initial_state)
            answer = final_state.get("answer") or final_state.get("raw_answer", "")
            if not answer:
                status = "empty"

            # Sync budget counter from client
            with self._budget_lock:
                self._budget_used = max(self._budget_used, self._client_b.budget_used)
        except Exception as exc:
            logger.error("[Track B] Error on %s: %s", sid, exc)
            answer = ""
            status = "error"
        elapsed = time.perf_counter() - t0
        logger.info(
            "[Track B] %s → %s  (%.1fs, status=%s)", sid, answer, elapsed, status
        )
        return sid, answer, elapsed, status
