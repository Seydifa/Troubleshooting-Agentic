"""
state.py — Shared Pipeline State

Defines the typed state objects passed between all LangGraph nodes.
Acts as the single contract across the full multi-agent pipeline.

Dependencies: None (stdlib only).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrackType(str, Enum):
    """Which competition track the question belongs to."""

    A = "A"
    B = "B"


class ProblemTypeA(str, Enum):
    """Classified problem category for Track A (5G / wireless)."""

    LATE_HANDOVER = "LATE_HANDOVER"
    INTERFERENCE = "INTERFERENCE"
    COVERAGE_HOLE = "COVERAGE_HOLE"
    TX_POWER_ISSUE = "TX_POWER_ISSUE"
    PDCCH_ISSUE = "PDCCH_ISSUE"
    NEIGHBOR_MISSING = "NEIGHBOR_MISSING"
    UNKNOWN = "UNKNOWN"


class TaskTypeB(str, Enum):
    """Decomposed task category for Track B (IP network)."""

    TOPOLOGY_RESTORE = "TOPOLOGY_RESTORE"
    PATH_QUERY = "PATH_QUERY"
    FAULT_DIAGNOSIS = "FAULT_DIAGNOSIS"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Track A State
# ---------------------------------------------------------------------------


class QuestionStateA(TypedDict, total=False):
    """Full state dict for one Track A question through the pipeline.

    Fields
    ------
    scenario_id : str
        Unique identifier for the scenario, sourced directly from test.json.
    question : str
        The raw question text.
    options : Dict[str, str]
        Candidate options, e.g. {"C1": "...", "C2": "...", ...}.
    tag : str
        Competition tag, e.g. "single-answer" or "multiple-answer".

    tool_cache : Dict[str, Any]
        Keyed results from the Tool Server (avoids duplicate API calls).
        Keys are endpoint names; values are the raw API responses.
    features : Dict[str, Any]
        Deterministically extracted numeric/boolean features (no LLM).
        Populated by feature_extraction_node.
    problem_type : ProblemTypeA
        Classified problem category (output of classify_problem_type()).
    rag_examples : List[str]
        Top-k similar training examples retrieved from the RAG index,
        already formatted as few-shot context strings.

    reasoning : str
        Chain-of-thought text produced by the analysis agent.
    raw_answer : str
        Raw LLM output before validation (e.g. "C5|C9|C11").
    answer : str
        Validated, canonical answer string.

    retry_count : int
        Number of times the analysis_node has been retried so far.
    budget_used : int
        Running total of API credits consumed for this question.
    error : Optional[str]
        Most recent validation error message, injected on retry.
    """

    # --- raw input ---
    scenario_id: str
    question: str
    options: Dict[str, str]
    tag: str

    # --- derived data ---
    tool_cache: Dict[str, Any]
    features: Dict[str, Any]
    problem_type: ProblemTypeA
    rag_examples: List[str]

    # --- agent output ---
    reasoning: str
    raw_answer: str
    answer: str

    # --- control flow ---
    retry_count: int
    budget_used: int
    error: Optional[str]


# ---------------------------------------------------------------------------
# Track B State
# ---------------------------------------------------------------------------


class QuestionStateB(TypedDict, total=False):
    """Full state dict for one Track B question through the pipeline.

    Fields
    ------
    scenario_id : str
        Unique identifier for the scenario.
    question : str
        The raw question text.
    task_id : str
        Task identifier within the scenario.

    task_type : TaskTypeB
        Decomposed sub-task type (output of decompose_node).
    target_node : str
        Primary node to investigate (output of decompose_node).
    extra_context : Dict[str, Any]
        Additional structured context extracted by decompose_node, e.g.
        {candidate_nodes, destination_ip, faulty_node, ...}.

    topology_facts : List[Dict[str, Any]]
        Parsed LLDP neighbour entries from parse_node.
    routing_facts : List[Dict[str, Any]]
        Parsed IP routing-table entries from parse_node.
    interface_facts : List[Dict[str, Any]]
        Parsed interface-brief entries from parse_node.
    arp_facts : List[Dict[str, Any]]
        Parsed ARP table entries from parse_node.

    computed_topology : Dict[str, Any]
        Adjacency dict produced by build_topology_graph().
    computed_path : List[str]
        Ordered hop list produced by trace_path().
    fault_candidates : List[Dict[str, Any]]
        Candidate fault entries produced by detect_faults().

    tool_cache : Dict[str, Any]
        Raw (output, vendor, command_type) tuples keyed by cache key.
    budget_used : int
        Running total of API credits consumed for this question.

    reasoning : str
        Chain-of-thought text produced by the reasoning agent.
    raw_answer : str
        Raw LLM output before format validation.
    answer : str
        Validated, canonical answer string.

    retry_count : int
        Number of times reasoning_node / discovery_node has been retried.
    error : Optional[str]
        Most recent validation error message, injected on retry.
    """

    # --- raw input ---
    scenario_id: str
    question: str
    task_id: str

    # --- decomposed sub-task ---
    task_type: TaskTypeB
    target_node: str
    extra_context: Dict[str, Any]

    # --- parsed facts (from parse_node) ---
    topology_facts: List[Dict[str, Any]]
    routing_facts: List[Dict[str, Any]]
    interface_facts: List[Dict[str, Any]]
    arp_facts: List[Dict[str, Any]]

    # --- computed results (from compute_node) ---
    computed_topology: Dict[str, Any]
    computed_path: List[str]
    fault_candidates: List[Dict[str, Any]]

    # --- API call tracking ---
    tool_cache: Dict[str, Any]
    budget_used: int

    # --- agent output ---
    reasoning: str
    raw_answer: str
    answer: str

    # --- control flow ---
    retry_count: int
    error: Optional[str]


# ---------------------------------------------------------------------------
# Factory Functions
# ---------------------------------------------------------------------------


def make_initial_state_a(scenario: dict) -> QuestionStateA:
    """Build a zeroed-out QuestionStateA from a raw test.json scenario dict.

    Parameters
    ----------
    scenario : dict
        A single entry from test.json for Track A.  Expected keys:
        ``scenario_id``, ``question``, ``options``, ``tag``.

    Returns
    -------
    QuestionStateA
        All pipeline fields initialised to safe empty values so that
        every downstream node can unconditionally read them.
    """
    task = scenario.get("task", {})
    options_list = task.get("options", [])
    options_dict = {
        opt["id"]: opt["label"]
        for opt in options_list
        if "id" in opt and "label" in opt
    }
    return QuestionStateA(
        # raw input
        scenario_id=scenario.get("scenario_id", ""),
        question=task.get("description", ""),
        options=options_dict,
        tag=scenario.get("tag", ""),
        # derived data
        tool_cache={},
        features={},
        problem_type=ProblemTypeA.UNKNOWN,
        rag_examples=[],
        # agent output
        reasoning="",
        raw_answer="",
        answer="",
        # control flow
        retry_count=0,
        budget_used=0,
        error=None,
    )


def make_initial_state_b(scenario: dict) -> QuestionStateB:
    """Build a zeroed-out QuestionStateB from a raw test.json scenario dict.

    Parameters
    ----------
    scenario : dict
        A single entry from test.json for Track B.  Expected keys:
        ``scenario_id``, ``question``, ``task_id``.

    Returns
    -------
    QuestionStateB
        All pipeline fields initialised to safe empty values so that
        every downstream node can unconditionally read them.
    """
    task = scenario.get("task", {})
    return QuestionStateB(
        # raw input
        scenario_id=scenario.get("scenario_id", ""),
        question=task.get("question", ""),
        task_id=str(task.get("id", "")),
        # decomposed sub-task
        task_type=TaskTypeB.UNKNOWN,
        target_node="",
        extra_context={},
        # parsed facts
        topology_facts=[],
        routing_facts=[],
        interface_facts=[],
        arp_facts=[],
        # computed results
        computed_topology={},
        computed_path=[],
        fault_candidates=[],
        # API call tracking
        tool_cache={},
        budget_used=0,
        # agent output
        reasoning="",
        raw_answer="",
        answer="",
        # control flow
        retry_count=0,
        error=None,
    )
