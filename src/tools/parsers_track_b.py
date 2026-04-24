"""
parsers_track_b.py — Centralized Parser Layer with LLM Normalization

Pipeline:
    Raw CLI output + vendor tag
        → VendorContextBuilder  (pure Python)
        → ParserAgent           (LLM, JSON-only, temperature=0)
        → SchemaValidator       (pure Python, port normalization, retry once)

Dependencies: requests, re, json, langchain_ollama, langchain_openai, state,
              prompts.system_prompts
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Port Normalization
# ---------------------------------------------------------------------------

_PORT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"Ten-GigabitEthernet(\S+)", re.I), r"XGE\1"),
    (re.compile(r"TenGigabitEthernet(\S+)", re.I), r"XGE\1"),
    (re.compile(r"GigabitEthernet(\S+)", re.I), r"GE\1"),
    (re.compile(r"Ethernet(\S+)", re.I), r"Eth\1"),
    (re.compile(r"LoopBack(\S+)", re.I), r"Loop\1"),
    (re.compile(r"Gig\s+(\S+)", re.I), r"GE\1"),
    (re.compile(r"Gi(\S+)", re.I), r"GE\1"),
]


def _normalize_port(port_str: str) -> str:
    """Canonicalize port names to their short form.

    Examples
    --------
    GigabitEthernet1/0/1       → GE1/0/1
    Ten-GigabitEthernet1/0/1   → XGE1/0/1
    Ethernet1/0/1              → Eth1/0/1
    Gi0/0/1                    → GE0/0/1
    """
    if not port_str:
        return port_str
    s = port_str.strip()
    for pattern, repl in _PORT_PATTERNS:
        new_s = pattern.sub(repl, s)
        if new_s != s:
            return new_s
    return s


# ---------------------------------------------------------------------------
# Canonical schemas — used by SchemaValidator
# ---------------------------------------------------------------------------

_REQUIRED_KEYS: Dict[str, List[str]] = {
    "lldp_neighbors": ["local_port", "remote_node", "remote_port"],
    "routing_table": ["prefix", "next_hop", "interface", "protocol"],
    "interface_brief": ["port", "ip", "status"],
    "arp_table": ["ip", "mac", "port"],
}

_PORT_FIELDS: Dict[str, List[str]] = {
    "lldp_neighbors": ["local_port", "remote_port"],
    "routing_table": ["interface"],
    "interface_brief": ["port"],
    "arp_table": ["port"],
}


# ---------------------------------------------------------------------------
# TrackBClient
# ---------------------------------------------------------------------------


class TrackBClient:
    """Cached HTTP wrapper for POST /api/agent/execute.

    Tracks ``budget_used`` counter (Phase 1 daily limit: 1000).
    Returns ``(raw_output, vendor, command_type)`` tuples.
    """

    def __init__(self, base_url: str, daily_limit: int = 1000):
        self._base_url = base_url.rstrip("/")
        self._daily_limit = daily_limit
        self.budget_used: int = 0
        self._cache: Dict[str, Tuple[str, str, str]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, scenario_id: str, node: str, command: str) -> str:
        raw = f"{scenario_id}:{node}:{command}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _map_command_type(self, command: str) -> str:
        """Infer command_type from a CLI command string."""
        cmd_lower = command.lower()
        if "lldp" in cmd_lower:
            return "lldp_neighbors"
        if "routing" in cmd_lower or "route" in cmd_lower:
            return "routing_table"
        if "arp" in cmd_lower:
            return "arp_table"
        if "interface" in cmd_lower or "brief" in cmd_lower:
            return "interface_brief"
        return "unknown"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def budget_remaining(self) -> int:
        return max(0, self._daily_limit - self.budget_used)

    def execute(
        self,
        task_id: str,
        node: str,
        command: str,
    ) -> Tuple[str, str, str]:
        """Issue a CLI command via the Track B API.

        Parameters
        ----------
        task_id : str
            The integer task ID from ``scenario["task"]["id"]``, sent as
            ``question_number`` in the POST body.
        node : str
            Target network device name (``device_name`` in the API).
        command : str
            CLI command string.

        Returns
        -------
        (raw_output, vendor, command_type)
        """
        key = self._cache_key(task_id, node, command)
        if key in self._cache:
            return self._cache[key]

        if self.budget_used >= self._daily_limit:
            logger.warning(
                "TrackBClient: budget exhausted (%d/%d)",
                self.budget_used,
                self._daily_limit,
            )
            return ("", "unknown", self._map_command_type(command))

        url = f"{self._base_url}/api/agent/execute"
        try:
            question_number = int(task_id) if task_id else 0
        except (TypeError, ValueError):
            question_number = 0
        payload = {
            "device_name": node,
            "command": command,
            "question_number": question_number,
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_output = data.get("result", "")
            vendor = data.get("vendor", "unknown").lower()
            command_type = data.get("command_type") or self._map_command_type(command)
            self.budget_used += 1
        except Exception as exc:
            logger.warning("TrackBClient POST %s failed: %s", url, exc)
            raw_output, vendor = "", "unknown"
            command_type = self._map_command_type(command)

        result = (raw_output, vendor, command_type)
        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# VendorContextBuilder
# ---------------------------------------------------------------------------


class VendorContextBuilder:
    """Select the matching VENDOR_PARSER_SKILL section for a (vendor, command_type) pair."""

    @staticmethod
    def build(
        vendor: str,
        command_type: str,
        raw_output: str,
    ) -> Dict[str, str]:
        """Return a context dict for the ParserAgent.

        Parameters
        ----------
        vendor : str
        command_type : str
        raw_output : str

        Returns
        -------
        dict with keys: vendor, command_type, skill_section, raw_output
        """
        from src.prompts.system_prompts import get_parser_skill_section

        skill_section = get_parser_skill_section(vendor, command_type)
        return {
            "vendor": vendor,
            "command_type": command_type,
            "skill_section": skill_section,
            "raw_output": raw_output,
        }


# ---------------------------------------------------------------------------
# ParserAgent
# ---------------------------------------------------------------------------


class ParserAgent:
    """LLM-based CLI output parser (temp=0, JSON-only).

    Uses the relevant VENDOR_PARSER_SKILL section as its system context.
    Returns a parsed Python list, or ``[]`` on failure.
    """

    def __init__(self):
        from src.llm import get_parser_llm

        self._llm = get_parser_llm()

    def parse(
        self,
        context: Dict[str, str],
        error_feedback: str = "",
    ) -> List[Dict[str, Any]]:
        """Run the parser LLM on the given context.

        Parameters
        ----------
        context : dict
            Output of VendorContextBuilder.build().
        error_feedback : str
            If retrying, include the previous validation error.

        Returns
        -------
        list[dict] or []
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.prompts.system_prompts import (
            TRACK_B_PARSER_SYSTEM,
            build_parser_prompt,
        )

        system_msg = SystemMessage(content=TRACK_B_PARSER_SYSTEM)
        human_content = build_parser_prompt(
            raw_output=context["raw_output"],
            vendor=context["vendor"],
            command_type=context["command_type"],
        )
        if error_feedback:
            human_content += f"\n\nPrevious attempt failed validation:\n{error_feedback}\nPlease fix and retry."
        # Thinking mode disabled via think=False in ChatOllama

        human_msg = HumanMessage(content=human_content)

        try:
            response = self._llm.invoke([system_msg, human_msg])
            raw_text = (
                response.content if hasattr(response, "content") else str(response)
            )
            if isinstance(raw_text, list):
                raw_text = "\n".join(
                    b.get("text", "")
                    if isinstance(b, dict) and b.get("type") == "text"
                    else b
                    if isinstance(b, str)
                    else ""
                    for b in raw_text
                )
            return _extract_json_list(raw_text)
        except Exception as exc:
            logger.warning("ParserAgent.parse failed: %s", exc)
            return []

    def parse_batch(
        self,
        contexts: List[Dict[str, str]],
        error_feedbacks: Optional[List[str]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """Batch-parse multiple CLI outputs in a single ``llm.batch()`` call.

        Parameters
        ----------
        contexts : list[dict]
            Each element is the output of ``VendorContextBuilder.build()``.
        error_feedbacks : list[str], optional
            Per-context retry error messages. Defaults to empty strings.

        Returns
        -------
        list[list[dict]]
            One parsed result list per input context.
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.prompts.system_prompts import (
            TRACK_B_PARSER_SYSTEM,
            build_parser_prompt,
        )

        if not contexts:
            return []
        if error_feedbacks is None:
            error_feedbacks = [""] * len(contexts)

        message_batches: List[list] = []
        for context, error_fb in zip(contexts, error_feedbacks):
            human_content = build_parser_prompt(
                raw_output=context["raw_output"],
                vendor=context["vendor"],
                command_type=context["command_type"],
            )
            if error_fb:
                human_content += (
                    f"\n\nPrevious attempt failed validation:\n{error_fb}"
                    "\nPlease fix and retry."
                )
            # Thinking mode disabled via think=False — no prompt-level switch needed
            message_batches.append(
                [
                    SystemMessage(content=TRACK_B_PARSER_SYSTEM),
                    HumanMessage(content=human_content),
                ]
            )

        try:
            responses = self._llm.batch(message_batches)

            def _resp_text(r) -> str:
                c = r.content if hasattr(r, "content") else str(r)
                if isinstance(c, list):
                    return "\n".join(
                        b.get("text", "")
                        if isinstance(b, dict) and b.get("type") == "text"
                        else b
                        if isinstance(b, str)
                        else ""
                        for b in c
                    )
                return c

            return [_extract_json_list(_resp_text(r)) for r in responses]
        except Exception as exc:
            logger.warning(
                "ParserAgent.parse_batch failed: %s — falling back to sequential", exc
            )
            return [self.parse(ctx, ef) for ctx, ef in zip(contexts, error_feedbacks)]


def _extract_json_list(text: str) -> List[Dict[str, Any]]:
    """Extract the first JSON array from an LLM response string."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = text.rstrip("`").strip()
    # Find the outermost [ ... ]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("JSON decode failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# SchemaValidator
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Validate and normalize parser output against the canonical schemas."""

    @staticmethod
    def validate(
        data: List[Dict[str, Any]],
        command_type: str,
    ) -> List[Dict[str, Any]]:
        """Validate ``data`` against the canonical schema for ``command_type``.

        1. Checks every entry has the required keys.
        2. Normalizes all port-name fields via ``_normalize_port()``.
        3. Returns ``[]`` if any entry is structurally invalid.

        Parameters
        ----------
        data : list[dict]
        command_type : str

        Returns
        -------
        list[dict] — validated and port-normalized, or [] on failure.
        """
        required = _REQUIRED_KEYS.get(command_type, [])
        port_fields = _PORT_FIELDS.get(command_type, [])

        if not isinstance(data, list):
            return []

        result = []
        for entry in data:
            if not isinstance(entry, dict):
                return []
            # Check required keys
            if not all(k in entry for k in required):
                return []
            # Normalize port fields
            row = dict(entry)
            for field in port_fields:
                if field in row and row[field]:
                    row[field] = _normalize_port(str(row[field]))
            result.append(row)

        return result


# ---------------------------------------------------------------------------
# High-level parse helper
# ---------------------------------------------------------------------------


def parse_cli_output(
    raw_output: str,
    vendor: str,
    command_type: str,
    parser_agent: Optional[ParserAgent] = None,
) -> List[Dict[str, Any]]:
    """Full parse pipeline: VendorContextBuilder → ParserAgent → SchemaValidator.

    Retries once with error feedback if the first attempt fails validation.

    Parameters
    ----------
    raw_output : str
    vendor : str
    command_type : str
    parser_agent : ParserAgent, optional
        If None, a new instance is created (not recommended for batch use).

    Returns
    -------
    list[dict] or []
    """
    if parser_agent is None:
        parser_agent = ParserAgent()

    context = VendorContextBuilder.build(vendor, command_type, raw_output)

    # First attempt
    parsed = parser_agent.parse(context)
    validated = SchemaValidator.validate(parsed, command_type)
    if validated:
        return validated

    # Retry once with error feedback
    error_msg = (
        f"Output did not match schema for {command_type}. "
        f"Required keys: {_REQUIRED_KEYS.get(command_type, [])}. "
        f"Got: {parsed[:2] if parsed else 'empty list'}."
    )
    parsed2 = parser_agent.parse(context, error_feedback=error_msg)
    validated2 = SchemaValidator.validate(parsed2, command_type)
    return validated2  # Returns [] sentinel if still invalid


def batch_parse_cli_outputs(
    entries: List[Dict[str, Any]],
    parser_agent: Optional[ParserAgent] = None,
) -> List[List[Dict[str, Any]]]:
    """Batch equivalent of ``parse_cli_output`` for multiple entries.

    Sends all first-pass parse requests in a single ``llm.batch()`` call, then
    retries only the entries that fail schema validation in a second batch call.
    This replaces a sequential for-loop of N×``llm.invoke()`` calls with at
    most 2 ``llm.batch()`` calls regardless of N.

    Parameters
    ----------
    entries : list[dict]
        Each dict must have keys: ``raw_output``, ``vendor``, ``command_type``.
    parser_agent : ParserAgent, optional
        Shared instance. A new one is created if not supplied.

    Returns
    -------
    list[list[dict]]
        One validated result list per entry (empty list on failure).
    """
    if parser_agent is None:
        parser_agent = ParserAgent()
    if not entries:
        return []

    contexts = [
        VendorContextBuilder.build(
            e.get("vendor", "unknown"),
            e.get("command_type", ""),
            e.get("raw_output", ""),
        )
        for e in entries
    ]

    # ── First pass: batch parse ───────────────────────────────────────────────
    first_pass = parser_agent.parse_batch(contexts)
    validated = [
        SchemaValidator.validate(parsed, ctx["command_type"])
        for parsed, ctx in zip(first_pass, contexts)
    ]

    # ── Second pass: retry only failures ─────────────────────────────────────
    retry_indices = [i for i, v in enumerate(validated) if not v]
    if retry_indices:
        retry_contexts = [contexts[i] for i in retry_indices]
        retry_errors = [
            (
                f"Output did not match schema for {contexts[i]['command_type']}. "
                f"Required keys: {_REQUIRED_KEYS.get(contexts[i]['command_type'], [])}. "
                f"Got: {first_pass[i][:2] if first_pass[i] else 'empty list'}."
            )
            for i in retry_indices
        ]
        retry_results = parser_agent.parse_batch(retry_contexts, retry_errors)
        for pos, idx in enumerate(retry_indices):
            validated[idx] = SchemaValidator.validate(
                retry_results[pos], contexts[idx]["command_type"]
            )

    return validated
