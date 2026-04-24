"""
agents_track_a.py — LangGraph Track A Pipeline (5G Wireless Troubleshooting)

Pipeline: retrieval_node → feature_extraction_node → rag_retrieval_node
          → analysis_node → validation_node → (END | retry)

Dependencies: langgraph, langchain_ollama, langchain_openai,
              state, tools.tools_track_a, rag, llm, prompts.system_prompts
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.state import ProblemTypeA, QuestionStateA
from src.tools.tools_track_a import (
    TrackAClient,
    build_feature_vector,
    classify_problem_type,
    extract_features_from_rows,
)
from src.prompts.system_prompts import (
    TRACK_A_ANALYSIS_SYSTEM,
    build_track_a_analysis_prompt,
)
from src.llm import get_reasoning_llm

logger = logging.getLogger(__name__)


def _extract_llm_text(resp) -> str:
    """Return plain text from an LLM response, handling both string and list content.

    Newer versions of langchain-ollama return a list of content blocks when
    a Qwen3 thinking model is used (one 'thinking' block + one 'text' block).
    This helper extracts only the text blocks and strips any residual
    ``<think>...</think>`` tags from string responses.
    """
    content = resp.content if hasattr(resp, "content") else str(resp)
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            if isinstance(block, dict) and block.get("type") == "text"
            else block
            if isinstance(block, str)
            else ""
            for block in content
        ]
        return "\n".join(p for p in parts if p)
    # Strip <think>...</think> blocks (safety net for thinking-mode leakage)
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def retrieval_node(state: QuestionStateA, *, client: TrackAClient) -> QuestionStateA:
    """Fetch ALL tool-server data upfront in parallel. No LLM.

    Issues the three independent HTTP calls concurrently so IO wait does not
    compound.  Populates ``state["tool_cache"]``.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sid = state.get("scenario_id", "")
    cache = dict(state.get("tool_cache", {}))

    endpoints = {
        "throughput_logs": client.throughput_logs,
        "user_plane_data": client.user_plane_data,
        "config_data": client.config_data,
    }
    missing = {name: fn for name, fn in endpoints.items() if name not in cache}
    if not missing:
        return {**state, "tool_cache": cache}

    def _fetch(name: str, fn) -> tuple[str, dict]:
        try:
            return name, fn(sid)
        except Exception as exc:
            logger.warning("retrieval_node: %s failed for %s: %s", name, sid, exc)
            return name, {}

    with ThreadPoolExecutor(max_workers=len(missing)) as executor:
        futures = {executor.submit(_fetch, n, f): n for n, f in missing.items()}
        for future in as_completed(futures):
            name, result = future.result()
            cache[name] = result

    return {**state, "tool_cache": cache}


def feature_extraction_node(state: QuestionStateA) -> QuestionStateA:
    """Pure-Python math on tool_cache. No LLM, no API calls.

    Populates ``state["features"]`` and ``state["problem_type"]``.
    """
    cache = state.get("tool_cache", {})
    up_rows = cache.get("user_plane_data", {}).get("rows", [])
    config_rows = cache.get("config_data", {}).get("rows", [])

    features: Dict[str, Any] = extract_features_from_rows(up_rows, config_rows)
    problem_type_str = classify_problem_type(features)

    logger.debug(
        "[Track A] [%s] features = %s  problem_type = %s",
        state.get("scenario_id", ""),
        features,
        problem_type_str,
    )

    return {
        **state,
        "features": features,
        "problem_type": ProblemTypeA(problem_type_str),
    }


def rag_retrieval_node(state: QuestionStateA, *, rag) -> QuestionStateA:
    """KNN lookup in TabularRAG. No LLM, no API calls.

    Populates ``state["rag_examples"]``.
    """
    features = state.get("features", {})
    fv = build_feature_vector(features)
    try:
        context_str = rag.format_context(fv)
        rag_examples = [context_str] if context_str else []
    except Exception as exc:
        logger.warning("rag_retrieval_node failed: %s", exc)
        rag_examples = []
    return {**state, "rag_examples": rag_examples}


def analysis_node(state: QuestionStateA, *, llm) -> QuestionStateA:
    """Single LLM call: produce chain-of-thought + raw_answer."""
    from langchain_core.messages import HumanMessage, SystemMessage

    features = state.get("features", {})
    rag_ctx = "\n\n".join(state.get("rag_examples", []))
    options = state.get("options", {})
    tag = state.get("tag", "single-answer")
    error_msg = state.get("error")

    human_content = build_track_a_analysis_prompt(features, rag_ctx, options, tag)
    if error_msg:
        human_content += f"\n\n⚠️ Previous answer was INVALID: {error_msg}\nPlease correct your answer."
    # /no_think disables Qwen3 extended thinking — must be on the same line (no preceding newline)
    human_content = human_content.rstrip() + " /no_think"

    messages = [
        SystemMessage(content=TRACK_A_ANALYSIS_SYSTEM),
        HumanMessage(content=human_content),
    ]

    logger.debug(
        "[Track A] [%s] analysis_node prompt (retry=%d):\n%s",
        state.get("scenario_id", ""),
        state.get("retry_count", 0),
        human_content,
    )

    try:
        resp = llm.invoke(messages)
        raw_text = _extract_llm_text(resp)
    except Exception as exc:
        logger.error("analysis_node LLM call failed: %s", exc)
        raw_text = ""

    logger.debug(
        "[Track A] [%s] LLM raw response:\n%s",
        state.get("scenario_id", ""),
        raw_text,
    )

    # 1. Try to find explicit ANSWER: label (last occurrence wins)
    raw_answer = ""
    for line in reversed(raw_text.splitlines()):
        if "ANSWER:" in line.upper():
            raw_answer = line.split("ANSWER:", 1)[-1].strip()
            break
    # 2. Fallback: if no ANSWER: label, pick the last Cn codes found in the text
    if not raw_answer:
        all_codes = re.findall(r"C\d+", raw_text)
        if all_codes:
            unique = sorted(set(int(c[1:]) for c in all_codes))
            raw_answer = "|".join(f"C{n}" for n in unique)

    logger.debug(
        "[Track A] [%s] extracted raw_answer: %r",
        state.get("scenario_id", ""),
        raw_answer,
    )

    return {
        **state,
        "reasoning": raw_text,
        "raw_answer": raw_answer,
        "retry_count": state.get("retry_count", 0),
    }


def validation_node(state: QuestionStateA) -> QuestionStateA:
    """Pure-Python format validation. No LLM.

    Checks:
    - Format: C\\d+(\\|C\\d+)*
    - Ascending order
    - Count matches tag (single → exactly 1, multiple → 2-4)
    """
    raw = state.get("raw_answer", "").strip()
    tag = state.get("tag", "single-answer")

    # Extract Cn codes
    codes = re.findall(r"C\d+", raw)
    numbers = [int(c[1:]) for c in codes]

    error: str | None = None

    if not codes:
        error = f"No valid Cn codes found in: '{raw}'"
    elif numbers != sorted(numbers):
        error = f"Codes not in ascending order: {codes}"
    elif "single" in tag and len(codes) != 1:
        error = f"single-answer tag requires exactly 1 code, got {len(codes)}: {codes}"
    elif "multiple" in tag and len(codes) not in (2, 4):
        error = f"multiple-answer tag requires exactly 2 or 4 codes, got {len(codes)}: {codes}"

    if error is None:
        canonical = "|".join(f"C{n}" for n in sorted(numbers))
        logger.debug(
            "[Track A] [%s] validation PASSED → answer: %s",
            state.get("scenario_id", ""),
            canonical,
        )
        return {**state, "answer": canonical, "error": None}
    else:
        logger.debug(
            "[Track A] [%s] validation FAILED (retry %d): %s",
            state.get("scenario_id", ""),
            state.get("retry_count", 0) + 1,
            error,
        )
        return {
            **state,
            "error": error,
            "retry_count": state.get("retry_count", 0) + 1,
        }


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------


def _route_after_validation(state: QuestionStateA) -> str:
    if state.get("error") is None:
        return "end"
    if state.get("retry_count", 0) < 2:
        return "retry"
    # Give up — use whatever we have
    return "end"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_graph_a(client: TrackAClient, rag) -> Any:
    """Build and compile the Track A LangGraph StateGraph.

    Parameters
    ----------
    client : TrackAClient
    rag : TabularRAG

    Returns
    -------
    CompiledGraph
    """
    llm = get_reasoning_llm()

    graph = StateGraph(QuestionStateA)

    # Register nodes (use closures to inject dependencies)
    graph.add_node("retrieval", lambda s: retrieval_node(s, client=client))
    graph.add_node("feature_extraction", feature_extraction_node)
    graph.add_node("rag_retrieval", lambda s: rag_retrieval_node(s, rag=rag))
    graph.add_node("analysis", lambda s: analysis_node(s, llm=llm))
    graph.add_node("validation", validation_node)

    # Edges
    graph.set_entry_point("retrieval")
    graph.add_edge("retrieval", "feature_extraction")
    graph.add_edge("feature_extraction", "rag_retrieval")
    graph.add_edge("rag_retrieval", "analysis")
    graph.add_edge("analysis", "validation")

    # Conditional: valid → END, invalid+retry < 2 → analysis
    graph.add_conditional_edges(
        "validation",
        _route_after_validation,
        {"end": END, "retry": "analysis"},
    )

    return graph.compile()
