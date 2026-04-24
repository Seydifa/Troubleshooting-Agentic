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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

        # Track A — sequential
        for scenario in track_a_scenarios:
            sid, answer = self._run_question_a(scenario)
            results_a[sid] = answer

        # Track B — max 2 concurrent
        if track_b_scenarios:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(self._run_question_b, scenario): scenario.get(
                        "scenario_id", ""
                    )
                    for scenario in track_b_scenarios
                }
                for future in as_completed(futures):
                    sid_b = futures[future]
                    try:
                        _, answer = future.result()
                        results_b[sid_b] = answer
                    except Exception as exc:
                        logger.error("Track B scenario %s failed: %s", sid_b, exc)
                        results_b[sid_b] = ""

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
        _, answer = self._run_question_a(scenario)
        return answer

    def run_question_b(self, scenario: Dict[str, Any]) -> str:
        """Public wrapper: run Track B for one scenario, return answer string."""
        _, answer = self._run_question_b(scenario)
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

    def _run_question_a(self, scenario: Dict[str, Any]) -> tuple[str, str]:
        """Run the Track A LangGraph for one scenario.

        Returns (scenario_id, answer_string).
        """
        sid = scenario.get("scenario_id", "")
        logger.info("[Track A] Processing %s", sid)
        try:
            initial_state = make_initial_state_a(scenario)
            final_state: QuestionStateA = self._graph_a.invoke(initial_state)
            answer = final_state.get("answer") or final_state.get("raw_answer", "")
        except Exception as exc:
            logger.error("[Track A] Error on %s: %s", sid, exc)
            answer = ""
        logger.info("[Track A] %s → %s", sid, answer)
        return sid, answer

    def _run_question_b(self, scenario: Dict[str, Any]) -> tuple[str, str]:
        """Run the Track B LangGraph for one scenario (thread-safe budget check).

        Returns (scenario_id, answer_string).
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
                return sid, ""

        logger.info("[Track B] Processing %s", sid)
        try:
            initial_state = make_initial_state_b(scenario)
            final_state: QuestionStateB = self._graph_b.invoke(initial_state)
            answer = final_state.get("answer") or final_state.get("raw_answer", "")

            # Sync budget counter from client
            with self._budget_lock:
                self._budget_used = max(self._budget_used, self._client_b.budget_used)
        except Exception as exc:
            logger.error("[Track B] Error on %s: %s", sid, exc)
            answer = ""

        logger.info("[Track B] %s → %s", sid, answer)
        return sid, answer
