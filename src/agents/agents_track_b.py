"""
agents_track_b.py — LangGraph Track B Pipeline (IP Network Troubleshooting)

Pipeline: decompose_node → discovery_node → parse_node → compute_node
          → reasoning_node → format_validation_node → (END | retry)

Handles three task types: TOPOLOGY_RESTORE, PATH_QUERY, FAULT_DIAGNOSIS.

Dependencies: langgraph, langchain_ollama, langchain_openai,
              state, tools.parsers_track_b, tools.compute_track_b,
              llm, prompts.system_prompts
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from src.state import QuestionStateB, TaskTypeB
from src.tools.parsers_track_b import (
    ParserAgent,
    TrackBClient,
    batch_parse_cli_outputs,
)
from src.tools.compute_track_b import (
    build_topology_graph,
    detect_faults,
    find_links_for_node,
    format_links,
    merge_topology_graphs,
    reconcile_arp_vs_lldp,
    trace_path,
)
from src.prompts.system_prompts import (
    TRACK_B_DECOMPOSE_SYSTEM,
    TRACK_B_REASONING_SYSTEM,
    build_track_b_reasoning_prompt,
)
from src.llm import get_reasoning_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def decompose_node(state: QuestionStateB, *, llm) -> QuestionStateB:
    """LLM (small, JSON output): extract task_type, target_node, extra_context."""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=TRACK_B_DECOMPOSE_SYSTEM),
        # /no_think disables Qwen3 thinking mode — keeps JSON output clean
        HumanMessage(content=state.get("question", "") + " /no_think"),
    ]
    try:
        resp = llm.invoke(messages)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        # Strip markdown fences
        raw = re.sub(r"```(?:json)?", "", raw).rstrip("`").strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("decompose_node failed: %s", exc)
        data = {}

    task_type_str = data.get("task_type", "UNKNOWN")
    try:
        task_type = TaskTypeB(task_type_str)
    except ValueError:
        task_type = TaskTypeB.UNKNOWN

    return {
        **state,
        "task_type": task_type,
        "target_node": data.get("target_node", ""),
        "extra_context": data.get("extra_context", {}),
    }


def discovery_node(state: QuestionStateB, *, client: TrackBClient) -> QuestionStateB:
    """Pure HTTP — issue CLI commands, store raw (output, vendor, command_type) in tool_cache.

    No LLM calls. Budget-guarded.
    """
    task_id = state.get("task_id", "")
    task_type = state.get("task_type", TaskTypeB.UNKNOWN)
    target_node = state.get("target_node", "")
    extra = state.get("extra_context", {})
    budget = state.get("budget_used", 0)
    tool_cache = dict(state.get("tool_cache", {}))

    budget_limit = int(os.getenv("BUDGET_LIMIT", "1000"))

    def execute(node: str, command: str, key: str):
        nonlocal budget
        if key in tool_cache:
            return
        if budget >= budget_limit:
            logger.warning("discovery_node: budget exhausted")
            return
        raw, vendor, cmd_type = client.execute(task_id, node, command)
        tool_cache[key] = {
            "raw_output": raw,
            "vendor": vendor,
            "command_type": cmd_type,
            "node": node,
        }
        budget = client.budget_used

    if task_type == TaskTypeB.TOPOLOGY_RESTORE:
        candidate_nodes: List[str] = extra.get("candidate_nodes", [target_node]) or [
            target_node
        ]
        for node in candidate_nodes:
            execute(node, "display lldp neighbor brief", f"lldp:{node}")
        # ARP fallback for empty LLDP nodes
        for node in candidate_nodes:
            execute(node, "display arp", f"arp:{node}")
            execute(node, "display interface brief", f"iface:{node}")

    elif task_type == TaskTypeB.PATH_QUERY:
        source = extra.get("source_node", target_node)
        dest_ip = extra.get("destination_ip", "")
        execute(source, "display ip routing-table", f"rt:{source}")
        execute(source, "display interface brief", f"iface:{source}")
        # We'll hop through discovered next-hops in compute; queue initial neighbours
        for node in extra.get("candidate_nodes", []):
            execute(node, "display ip routing-table", f"rt:{node}")
            execute(node, "display interface brief", f"iface:{node}")
            execute(node, "display arp", f"arp:{node}")

    elif task_type == TaskTypeB.FAULT_DIAGNOSIS:
        faulty = extra.get("faulty_node", target_node)
        execute(faulty, "display interface brief", f"iface:{faulty}")
        execute(faulty, "display ip routing-table", f"rt:{faulty}")
        execute(faulty, "display current-configuration", f"cfg:{faulty}")

    return {**state, "tool_cache": tool_cache, "budget_used": budget}


def parse_node(state: QuestionStateB, *, parser_agent: ParserAgent) -> QuestionStateB:
    """Batch LLM iteration — normalise all cached CLI outputs in two llm.batch() passes.

    Replaces the old sequential for-loop (N × llm.invoke) with at most two
    llm.batch() calls: one first-pass for all entries, then a retry pass only
    for entries that failed schema validation.
    No API calls. Safe to retry independently of discovery.
    """
    tool_cache = state.get("tool_cache", {})

    entries_to_parse = [
        entry for entry in tool_cache.values() if entry.get("raw_output")
    ]

    if not entries_to_parse:
        return {
            **state,
            "topology_facts": [],
            "routing_facts": [],
            "interface_facts": [],
            "arp_facts": [],
        }

    all_results = batch_parse_cli_outputs(entries_to_parse, parser_agent)

    topology_facts: List[Dict[str, Any]] = []
    routing_facts: List[Dict[str, Any]] = []
    interface_facts: List[Dict[str, Any]] = []
    arp_facts: List[Dict[str, Any]] = []

    for entry, rows in zip(entries_to_parse, all_results):
        node = entry.get("node", "")
        command_type = entry.get("command_type", "")
        tagged = [{**row, "_node": node} for row in rows]

        if command_type == "lldp_neighbors":
            topology_facts.extend(tagged)
        elif command_type == "routing_table":
            routing_facts.extend(tagged)
        elif command_type == "interface_brief":
            interface_facts.extend(tagged)
        elif command_type == "arp_table":
            arp_facts.extend(tagged)

    return {
        **state,
        "topology_facts": topology_facts,
        "routing_facts": routing_facts,
        "interface_facts": interface_facts,
        "arp_facts": arp_facts,
    }


def compute_node(state: QuestionStateB) -> QuestionStateB:
    """Pure Python computation — graph/routing/fault logic. No LLM, no IO."""
    task_type = state.get("task_type", TaskTypeB.UNKNOWN)
    topo_facts = state.get("topology_facts", [])
    rt_facts = state.get("routing_facts", [])
    iface_facts = state.get("interface_facts", [])
    arp_facts = state.get("arp_facts", [])
    extra = state.get("extra_context", {})
    target_node = state.get("target_node", "")

    # --- Build per-node data structures ---

    # Group routing / interface / ARP facts by source node
    rt_by_node: Dict[str, List] = {}
    iface_by_node: Dict[str, List] = {}
    arp_by_node: Dict[str, List] = {}

    for row in rt_facts:
        n = row.get("_node", "")
        rt_by_node.setdefault(n, []).append(row)
    for row in iface_facts:
        n = row.get("_node", "")
        iface_by_node.setdefault(n, []).append(row)
    for row in arp_facts:
        n = row.get("_node", "")
        arp_by_node.setdefault(n, []).append(row)

    # Build topology graph from LLDP facts grouped by source node
    topo_by_node: Dict[str, List] = {}
    for row in topo_facts:
        n = row.get("_node", "")
        topo_by_node.setdefault(n, []).append(row)

    per_node_graphs = [
        build_topology_graph(entries, source_node=node)
        for node, entries in topo_by_node.items()
    ]
    full_graph = merge_topology_graphs(per_node_graphs)

    # Reconcile ARP vs LLDP
    lldp_links = [
        {
            "local_port": r.get("local_port"),
            "remote_node": r.get("remote_node"),
            "remote_port": r.get("remote_port"),
        }
        for r in topo_facts
    ]
    all_arp = [r for rows in arp_by_node.values() for r in rows]
    all_iface = [r for rows in iface_by_node.values() for r in rows]
    reconcile_arp_vs_lldp(lldp_links, all_arp, all_iface)  # Modifies in-place context

    # --- Task-specific computation ---
    computed_path: List[str] = []
    fault_candidates: List[Dict] = []

    if task_type == TaskTypeB.PATH_QUERY:
        source = extra.get("source_node", target_node)
        dest_ip = extra.get("destination_ip", "")
        if source and dest_ip:
            computed_path = trace_path(
                start=source,
                destination_ip=dest_ip,
                routing_tables=rt_by_node,
                interface_tables=iface_by_node,
                arp_tables=arp_by_node,
            )

    elif task_type == TaskTypeB.FAULT_DIAGNOSIS:
        faulty = extra.get("faulty_node", target_node)
        fault_candidates = detect_faults(
            interface_facts=iface_by_node.get(faulty, []),
            routing_facts=rt_by_node.get(faulty, []),
        )

    return {
        **state,
        "computed_topology": full_graph,
        "computed_path": computed_path,
        "fault_candidates": fault_candidates,
    }


def reasoning_node(state: QuestionStateB, *, llm) -> QuestionStateB:
    """Single LLM call with structured facts only. Produces raw_answer."""
    from langchain_core.messages import HumanMessage, SystemMessage

    error_msg = state.get("error")
    human_content = build_track_b_reasoning_prompt(
        question=state.get("question", ""),
        task_type=str(state.get("task_type", TaskTypeB.UNKNOWN)).split(".")[-1],
        topology=state.get("computed_topology", {}),
        routing=state.get("routing_facts", []),
        interfaces=state.get("interface_facts", []),
        faults=state.get("fault_candidates", []),
        computed_path=state.get("computed_path"),
        computed_topology=state.get("computed_topology"),
    )
    if error_msg:
        human_content += (
            f"\n\n⚠️ Previous answer was INVALID: {error_msg}\nPlease fix the format."
        )

    messages = [
        SystemMessage(content=TRACK_B_REASONING_SYSTEM),
        HumanMessage(content=human_content),
    ]
    try:
        resp = llm.invoke(messages)
        raw_text = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.error("reasoning_node LLM call failed: %s", exc)
        raw_text = ""

    raw_answer = raw_text
    for line in reversed(raw_text.splitlines()):
        if "ANSWER:" in line.upper():
            raw_answer = line.split("ANSWER:", 1)[-1].strip()
            break

    return {
        **state,
        "reasoning": raw_text,
        "raw_answer": raw_answer,
    }


def format_validation_node(state: QuestionStateB) -> QuestionStateB:
    """Pure-Python per-task-type regex validation."""
    raw = state.get("raw_answer", "").strip()
    task_type = state.get("task_type", TaskTypeB.UNKNOWN)
    retry = state.get("retry_count", 0)

    error: str | None = None

    if task_type == TaskTypeB.TOPOLOGY_RESTORE:
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        pattern = re.compile(
            r"^[A-Za-z0-9\-]+\([A-Za-z0-9/]+\)->[A-Za-z0-9\-]+\([A-Za-z0-9/]+\)$"
        )
        bad = [l for l in lines if not pattern.match(l)]
        if bad:
            error = f"Invalid topology lines: {bad[:3]}"
        elif not lines:
            error = "Empty topology answer"

    elif task_type == TaskTypeB.PATH_QUERY:
        if not re.match(
            r"^[A-Za-z0-9\-]+(->[ ]?[A-Za-z0-9\-]+)+$", raw.replace(" ", "")
        ):
            error = f"Invalid PATH_QUERY format: '{raw}'"

    elif task_type == TaskTypeB.FAULT_DIAGNOSIS:
        if not re.match(r"^[^;]+;[^;]+;[^;]+$", raw):
            error = f"Invalid FAULT_DIAGNOSIS format: '{raw}'"

    if error is None:
        return {**state, "answer": raw, "error": None}
    else:
        return {**state, "error": error, "retry_count": retry + 1}


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------


def _has_empty_facts(state: QuestionStateB) -> bool:
    return (
        not state.get("topology_facts")
        and not state.get("routing_facts")
        and not state.get("interface_facts")
    )


def _route_after_format(state: QuestionStateB) -> str:
    if state.get("error") is None:
        return "end"
    retry = state.get("retry_count", 0)
    if retry < 2:
        if _has_empty_facts(state):
            return "rediscover"
        return "retry"
    return "end"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_graph_b(client: TrackBClient) -> Any:
    """Build and compile the Track B LangGraph StateGraph.

    Parameters
    ----------
    client : TrackBClient

    Returns
    -------
    CompiledGraph
    """
    llm = get_reasoning_llm()
    parser_agent = ParserAgent()

    graph = StateGraph(QuestionStateB)

    graph.add_node("decompose", lambda s: decompose_node(s, llm=llm))
    graph.add_node("discovery", lambda s: discovery_node(s, client=client))
    graph.add_node("parse", lambda s: parse_node(s, parser_agent=parser_agent))
    graph.add_node("compute", compute_node)
    graph.add_node("reasoning", lambda s: reasoning_node(s, llm=llm))
    graph.add_node("format_validation", format_validation_node)

    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "discovery")
    graph.add_edge("discovery", "parse")
    graph.add_edge("parse", "compute")
    graph.add_edge("compute", "reasoning")
    graph.add_edge("reasoning", "format_validation")

    graph.add_conditional_edges(
        "format_validation",
        _route_after_format,
        {
            "end": END,
            "retry": "reasoning",
            "rediscover": "discovery",
        },
    )

    return graph.compile()
