"""
test_orchestrator.py — Tests for src/orchestrator.py.
Graph invocations are mocked — no LLM or HTTP calls.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator import Orchestrator
from src.state import make_initial_state_a, make_initial_state_b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(answers_a=None, answers_b=None):
    """Build an Orchestrator with mocked graphs that return fixed answers."""

    def _invoke_a(state):
        sid = state.get("scenario_id", "")
        ans = (answers_a or {}).get(sid, "C1")
        return {**state, "answer": ans}

    def _invoke_b(state):
        sid = state.get("scenario_id", "")
        ans = (answers_b or {}).get(sid, "R1->R2")
        return {**state, "answer": ans}

    graph_a = MagicMock()
    graph_a.invoke.side_effect = _invoke_a

    graph_b = MagicMock()
    graph_b.invoke.side_effect = _invoke_b

    client_b = MagicMock()
    client_b.budget_used = 0

    return Orchestrator(
        {
            "track_a_graph": graph_a,
            "track_b_graph": graph_b,
            "track_b_client": client_b,
            "daily_limit": 1000,
        }
    )


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "result.csv")
            Orchestrator.write_csv([{"ID": "s1", "Track A": "C1", "Track B": ""}], path)
            assert Path(path).exists()

    def test_correct_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "result.csv")
            rows = [
                {"ID": "s1", "Track A": "C3", "Track B": ""},
                {"ID": "s2", "Track A": "", "Track B": "R1->R2"},
            ]
            Orchestrator.write_csv(rows, path)
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                result = list(reader)
            assert result[0]["ID"] == "s1"
            assert result[0]["Track A"] == "C3"
            assert result[1]["Track B"] == "R1->R2"

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "result.csv")
            Orchestrator.write_csv([], path)
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                assert list(reader) == []

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "subdir" / "result.csv")
            Orchestrator.write_csv([{"ID": "s1", "Track A": "C1", "Track B": ""}], path)
            assert Path(path).exists()


# ---------------------------------------------------------------------------
# Orchestrator.run
# ---------------------------------------------------------------------------


class TestOrchestratorRun:
    def test_track_a_only(self):
        orc = _make_orchestrator(answers_a={"s1": "C5"})
        data = [{"scenario_id": "s1", "track": "A"}]
        results = orc.run(data)
        assert len(results) == 1
        assert results[0]["ID"] == "s1"
        assert results[0]["Track A"] == "C5"
        assert results[0]["Track B"] == ""

    def test_track_b_only(self):
        orc = _make_orchestrator(answers_b={"s2": "R1->R2->R3"})
        data = [{"scenario_id": "s2", "track": "B"}]
        results = orc.run(data)
        assert len(results) == 1
        assert results[0]["Track B"] == "R1->R2->R3"
        assert results[0]["Track A"] == ""

    def test_mixed_tracks(self):
        orc = _make_orchestrator(
            answers_a={"s1": "C3"},
            answers_b={"s2": "R1->R2"},
        )
        data = [
            {"scenario_id": "s1", "track": "A"},
            {"scenario_id": "s2", "track": "B"},
        ]
        results = orc.run(data)
        assert len(results) == 2
        ids = {r["ID"] for r in results}
        assert ids == {"s1", "s2"}

    def test_track_a_error_returns_empty_string(self):
        graph_a = MagicMock()
        graph_a.invoke.side_effect = RuntimeError("LLM failed")
        graph_b = MagicMock()
        graph_b.invoke.return_value = {}
        client_b = MagicMock()
        client_b.budget_used = 0

        orc = Orchestrator(
            {
                "track_a_graph": graph_a,
                "track_b_graph": graph_b,
                "track_b_client": client_b,
                "daily_limit": 1000,
            }
        )
        data = [{"scenario_id": "s1", "track": "A"}]
        results = orc.run(data)
        assert results[0]["Track A"] == ""

    def test_budget_exhausted_skips_track_b(self):
        graph_b = MagicMock()
        graph_b.invoke.return_value = {"answer": "R1->R2"}
        client_b = MagicMock()
        client_b.budget_used = 0

        orc = Orchestrator(
            {
                "track_a_graph": MagicMock(),
                "track_b_graph": graph_b,
                "track_b_client": client_b,
                "daily_limit": 0,  # budget already exhausted
            }
        )
        data = [{"scenario_id": "s1", "track": "B"}]
        results = orc.run(data)
        assert results[0]["Track B"] == ""

    def test_scenario_without_scenario_id_handled_gracefully(self):
        orc = _make_orchestrator()
        data = [{"track": "A"}]  # missing scenario_id
        results = orc.run(data)
        assert len(results) == 1

    def test_results_sorted_by_id(self):
        orc = _make_orchestrator(answers_a={"z-last": "C1", "a-first": "C2"})
        data = [
            {"scenario_id": "z-last", "track": "A"},
            {"scenario_id": "a-first", "track": "A"},
        ]
        results = orc.run(data)
        assert results[0]["ID"] == "a-first"
        assert results[1]["ID"] == "z-last"


# ---------------------------------------------------------------------------
# Public wrappers
# ---------------------------------------------------------------------------


class TestPublicWrappers:
    def test_run_question_a_returns_string(self):
        orc = _make_orchestrator(answers_a={"s1": "C7"})
        answer = orc.run_question_a({"scenario_id": "s1", "track": "A"})
        assert answer == "C7"

    def test_run_question_b_returns_string(self):
        orc = _make_orchestrator(answers_b={"s2": "R1->R2"})
        answer = orc.run_question_b({"scenario_id": "s2", "track": "B"})
        assert answer == "R1->R2"
