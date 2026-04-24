"""
test_prompts.py — Tests for src/prompts/system_prompts.py
(pure-Python string builders; no LLM).
"""

from __future__ import annotations

import pytest

from src.prompts.system_prompts import (
    build_parser_prompt,
    build_track_a_analysis_prompt,
    build_track_b_reasoning_prompt,
    get_parser_skill_section,
)


# ---------------------------------------------------------------------------
# get_parser_skill_section
# ---------------------------------------------------------------------------


class TestGetParserSkillSection:
    @pytest.mark.parametrize(
        "vendor,cmd_type",
        [
            ("huawei", "lldp_neighbors"),
            ("huawei", "routing_table"),
            ("huawei", "interface_brief"),
            ("huawei", "arp_table"),
            ("cisco", "lldp_neighbors"),
            ("cisco", "routing_table"),
            ("cisco", "interface_brief"),
            ("cisco", "arp_table"),
            ("h3c", "lldp_neighbors"),
            ("h3c", "routing_table"),
            ("h3c", "interface_brief"),
            ("h3c", "arp_table"),
        ],
    )
    def test_known_sections_return_content(self, vendor, cmd_type):
        section = get_parser_skill_section(vendor, cmd_type)
        assert isinstance(section, str)
        assert len(section) > 0

    def test_unknown_vendor_returns_empty(self):
        section = get_parser_skill_section("juniper", "lldp_neighbors")
        assert section == ""

    def test_unknown_command_type_returns_empty(self):
        section = get_parser_skill_section("huawei", "bgp_table")
        assert section == ""

    def test_section_contains_output_schema(self):
        section = get_parser_skill_section("huawei", "lldp_neighbors")
        assert "local_port" in section
        assert "remote_node" in section

    def test_case_insensitive_vendor(self):
        section_lower = get_parser_skill_section("huawei", "lldp_neighbors")
        section_upper = get_parser_skill_section("Huawei", "lldp_neighbors")
        assert section_lower == section_upper


# ---------------------------------------------------------------------------
# build_track_a_analysis_prompt
# ---------------------------------------------------------------------------


class TestBuildTrackAAnalysisPrompt:
    def test_contains_features(self):
        features = {"serving_rsrp": -90.0, "serving_sinr": 5.0}
        prompt = build_track_a_analysis_prompt(features, "", {}, "single-answer")
        assert "-90.0" in prompt or "serving_rsrp" in prompt

    def test_contains_options(self):
        options = {"C1": "Increase TX power", "C2": "Add neighbor relation"}
        prompt = build_track_a_analysis_prompt({}, "", options, "single-answer")
        assert "C1" in prompt
        assert "Increase TX power" in prompt

    def test_single_answer_instruction(self):
        prompt = build_track_a_analysis_prompt({}, "", {}, "single-answer")
        assert "ONE" in prompt or "one" in prompt.lower() or "exactly" in prompt.lower()

    def test_multiple_answer_instruction(self):
        prompt = build_track_a_analysis_prompt({}, "", {}, "multiple-answer")
        assert "2" in prompt or "pipe" in prompt.lower() or "4" in prompt

    def test_rag_context_included(self):
        rag_ctx = "--- Example (scenario_id=s1) ---\nANSWER: C5"
        prompt = build_track_a_analysis_prompt({}, rag_ctx, {}, "single-answer")
        assert "s1" in prompt

    def test_no_rag_context_shows_none_available(self):
        prompt = build_track_a_analysis_prompt({}, "", {}, "single-answer")
        assert "none available" in prompt.lower() or "(none)" in prompt.lower()

    def test_ends_with_answer_instruction(self):
        prompt = build_track_a_analysis_prompt({}, "", {}, "single-answer")
        assert "ANSWER:" in prompt


# ---------------------------------------------------------------------------
# build_parser_prompt
# ---------------------------------------------------------------------------


class TestBuildParserPrompt:
    def test_contains_raw_output(self):
        raw = "GE1/0/0  R2  GE0/0/1  120"
        prompt = build_parser_prompt(raw, "huawei", "lldp_neighbors")
        assert raw in prompt

    def test_contains_skill_section(self):
        prompt = build_parser_prompt("some output", "huawei", "lldp_neighbors")
        assert "local_port" in prompt

    def test_unknown_vendor_still_returns_prompt(self):
        prompt = build_parser_prompt("some output", "unknown", "lldp_neighbors")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ---------------------------------------------------------------------------
# build_track_b_reasoning_prompt
# ---------------------------------------------------------------------------


class TestBuildTrackBReasoningPrompt:
    def test_contains_question(self):
        prompt = build_track_b_reasoning_prompt(
            question="What is the path from R1 to 10.1.2.0/24?",
            task_type="PATH_QUERY",
            topology={},
            routing=[],
            interfaces=[],
            faults=[],
        )
        assert "What is the path from R1 to 10.1.2.0/24?" in prompt

    def test_contains_task_type(self):
        prompt = build_track_b_reasoning_prompt(
            question="q",
            task_type="FAULT_DIAGNOSIS",
            topology={},
            routing=[],
            interfaces=[],
            faults=[],
        )
        assert "FAULT_DIAGNOSIS" in prompt

    def test_computed_path_included(self):
        prompt = build_track_b_reasoning_prompt(
            question="q",
            task_type="PATH_QUERY",
            topology={},
            routing=[],
            interfaces=[],
            faults=[],
            computed_path=["R1", "R2", "R3"],
        )
        assert "R1" in prompt
        assert "R2" in prompt

    def test_computed_topology_included(self):
        topo = {"R1": [["GE1/0/0", "R2", "GE0/0/1"]]}
        prompt = build_track_b_reasoning_prompt(
            question="q",
            task_type="TOPOLOGY_RESTORE",
            topology=topo,
            routing=[],
            interfaces=[],
            faults=[],
            computed_topology=topo,
        )
        assert "R1" in prompt

    def test_ends_with_answer_instruction(self):
        prompt = build_track_b_reasoning_prompt(
            question="q",
            task_type="PATH_QUERY",
            topology={},
            routing=[],
            interfaces=[],
            faults=[],
        )
        assert "ANSWER:" in prompt
