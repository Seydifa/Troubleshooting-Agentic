"""
test_state.py — Tests for src/state.py enums and factory functions.
"""

from __future__ import annotations

import pytest

from src.state import (
    ProblemTypeA,
    QuestionStateA,
    QuestionStateB,
    TaskTypeB,
    TrackType,
    make_initial_state_a,
    make_initial_state_b,
)


class TestTrackType:
    def test_values(self):
        assert TrackType.A == "A"
        assert TrackType.B == "B"

    def test_from_string(self):
        assert TrackType("A") is TrackType.A
        assert TrackType("B") is TrackType.B


class TestProblemTypeA:
    def test_all_values_defined(self):
        expected = {
            "LATE_HANDOVER",
            "INTERFERENCE",
            "COVERAGE_HOLE",
            "TX_POWER_ISSUE",
            "PDCCH_ISSUE",
            "NEIGHBOR_MISSING",
            "UNKNOWN",
        }
        actual = {e.value for e in ProblemTypeA}
        assert expected == actual

    def test_unknown_default(self):
        assert ProblemTypeA.UNKNOWN.value == "UNKNOWN"


class TestTaskTypeB:
    def test_all_values_defined(self):
        expected = {"TOPOLOGY_RESTORE", "PATH_QUERY", "FAULT_DIAGNOSIS", "UNKNOWN"}
        actual = {e.value for e in TaskTypeB}
        assert expected == actual


class TestMakeInitialStateA:
    def test_basic_fields_populated(self, sample_scenario_a):
        state = make_initial_state_a(sample_scenario_a)
        assert state["scenario_id"] == "test-scenario-a-001"
        assert state["question"] == "Which optimization action should be taken?"
        assert state["tag"] == "single-answer"
        assert isinstance(state["options"], dict)
        assert len(state["options"]) == 4

    def test_defaults_zeroed(self, sample_scenario_a):
        state = make_initial_state_a(sample_scenario_a)
        assert state["tool_cache"] == {}
        assert state["features"] == {}
        assert state["rag_examples"] == []
        assert state["reasoning"] == ""
        assert state["raw_answer"] == ""
        assert state["answer"] == ""
        assert state["retry_count"] == 0
        assert state["budget_used"] == 0
        assert state["error"] is None

    def test_problem_type_default(self, sample_scenario_a):
        state = make_initial_state_a(sample_scenario_a)
        assert state["problem_type"] == ProblemTypeA.UNKNOWN

    def test_missing_keys_use_defaults(self):
        state = make_initial_state_a({})
        assert state["scenario_id"] == ""
        assert state["question"] == ""
        assert state["options"] == {}
        assert state["tag"] == ""


class TestMakeInitialStateB:
    def test_basic_fields_populated(self, sample_scenario_b):
        state = make_initial_state_b(sample_scenario_b)
        assert state["scenario_id"] == "test-scenario-b-001"
        assert state["question"] == "What is the path from R1 to 10.1.2.0/24?"
        assert state["task_id"] == "1"

    def test_defaults_zeroed(self, sample_scenario_b):
        state = make_initial_state_b(sample_scenario_b)
        assert state["task_type"] == TaskTypeB.UNKNOWN
        assert state["target_node"] == ""
        assert state["extra_context"] == {}
        assert state["topology_facts"] == []
        assert state["routing_facts"] == []
        assert state["interface_facts"] == []
        assert state["arp_facts"] == []
        assert state["computed_topology"] == {}
        assert state["computed_path"] == []
        assert state["fault_candidates"] == []
        assert state["tool_cache"] == {}
        assert state["budget_used"] == 0
        assert state["reasoning"] == ""
        assert state["raw_answer"] == ""
        assert state["answer"] == ""
        assert state["retry_count"] == 0
        assert state["error"] is None

    def test_missing_keys_use_defaults(self):
        state = make_initial_state_b({})
        assert state["scenario_id"] == ""
        assert state["task_id"] == ""
