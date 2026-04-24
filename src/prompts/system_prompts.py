"""
system_prompts.py — Centralized System Prompts & Skill Context

Single source of truth for all agent system prompts, telecom skill context,
and the VENDOR_PARSER_SKILL used by the ParserAgent.

Dependencies: None (stdlib only).
"""

from __future__ import annotations

import glob
import os
from typing import Dict, Any, List


# ---------------------------------------------------------------------------
# TRACK A — Skill Context (dynamically loaded, always injected into analysis agent)
# ---------------------------------------------------------------------------


def _load_track_a_skills() -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))
    file_path = os.path.join(base_dir, "skills", "track_a", "wireless_optimization.md")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "## TRACK A SKILL\nNo skills found."


TRACK_A_SKILL = _load_track_a_skills()

# ---------------------------------------------------------------------------
# TRACK B — Skill Context (dynamically loaded per task, injected into human prompt)
# ---------------------------------------------------------------------------


def _load_track_b_skills(task_type: str) -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))

    # Map typical tasks. Provide default if unknown.
    task_map = {
        "TOPOLOGY_RESTORE": "topology_restore.md",
        "PATH_QUERY": "path_query.md",
        "FAULT_DIAGNOSIS": "fault_diagnosis.md",
    }

    task_key = str(task_type).upper().split(".")[-1]
    filename = task_map.get(task_key, "fault_diagnosis.md")  # Fallback

    file_path = os.path.join(base_dir, "skills", "track_b", filename)

    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "## TRACK B SKILLS\nNo skills found."


# ---------------------------------------------------------------------------
# VENDOR_PARSER_SKILL — Centralized CLI format knowledge for ParserAgent
# ---------------------------------------------------------------------------

VENDOR_PARSER_SKILL = """
## VENDOR_PARSER_SKILL — CLI Output Normalization Guide

You are a structured data extraction agent. Your ONLY output is valid JSON.
No explanations, no markdown, no extra text — ONLY the JSON array.

---

### Port Normalization Rules (apply to ALL vendors)
| Raw form                         | Canonical form |
|----------------------------------|----------------|
| GigabitEthernet<n>               | GE<n>          |
| Ten-GigabitEthernet<n>           | XGE<n>         |
| TenGigabitEthernet<n>            | XGE<n>         |
| Ethernet<n>                      | Eth<n>         |
| GE<n>                            | GE<n>          |
| XGE<n>                           | XGE<n>         |
| Eth<n>                           | Eth<n>         |
| MEth<n>                          | MEth<n>        |
| LoopBack<n>                      | Loop<n>        |
| Vlanif<n>                        | Vlanif<n>      |

---

### [huawei:lldp_neighbors]
Command: `display lldp neighbor brief`
Template:
```
Local Intf     Neighbor ID        PortID           ExpTime
GE1/0/0        R2                 GE0/0/1          120
GE1/0/1        R3                 GE0/0/0          115
```
Field mapping:
- Local Intf → local_port (normalize)
- Neighbor ID → remote_node
- PortID → remote_port (normalize)

Skip: header line, separator lines, lines with no data.
Output schema: [{"local_port": str, "remote_node": str, "remote_port": str}]

---

### [huawei:routing_table]
Command: `display ip routing-table`
Template:
```
Route Flags: R - relay, D - download to fib
------------------------------------------------------------------------------
Routing Tables: Public
         Destinations : 8       Routes : 8

Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface
        0.0.0.0/0   Static  60   0          RD   10.1.1.2        GE1/0/0
      10.1.1.0/30   Direct  0    0          D    10.1.1.1        GE1/0/0
```
Field mapping:
- Destination/Mask → prefix (CIDR notation, e.g. "10.1.1.0/30")
- Proto → protocol
- NextHop → next_hop
- Interface → interface (normalize)

Skip header, separator, summary lines. Only extract route lines.
Output schema: [{"prefix": str, "next_hop": str, "interface": str, "protocol": str}]

---

### [huawei:interface_brief]
Command: `display interface brief`
Template:
```
PHY: Physical   *down: administratively down
InUti/OutUti: input utility/output utility

Interface            PHY   Protocol InUti OutUti   inErrors  outErrors
GE1/0/0              up    up       0%    0%       0         0
GE1/0/1              *down down     0%    0%       0         0
GE1/0/2              down  down     0%    0%       0         0
```
Field mapping:
- Interface → port (normalize)
- PHY column:
  - "up" + Protocol "up" → status: "up"
  - "*down" (any protocol) → status: "admin-down"
  - "down" + Protocol "down" → status: "down"
- IP Address: if present → ip, else ""

Output schema: [{"port": str, "ip": str, "status": str}]

---

### [huawei:arp_table]
Command: `display arp`
Template:
```
IP ADDRESS      MAC ADDRESS    EXPIRE(M) TYPE  INTERFACE     VPN-INSTANCE VLAN ID
10.1.1.2        0012-3456-7890 20        D     GE1/0/0
10.1.1.6        0012-3456-aabb --        S     GE1/0/1
```
Field mapping:
- IP ADDRESS → ip
- MAC ADDRESS → mac
- INTERFACE → port (normalize)

Skip header and separator lines.
Output schema: [{"ip": str, "mac": str, "port": str}]

---

### [cisco:lldp_neighbors]
Command: `show lldp neighbors` or `show cdp neighbors`
LLDP template:
```
Capability codes:
    (R) Router, (B) Bridge, ...

Device ID        Local Intf          Exp  Cap  Port ID
R2               Gi0/0/1             120  R    Gi0/0/0
R3               Gi0/0/2             115  R    Gi0/0/0
```
CDP template:
```
Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID
R2               Gig 0/1           165        R           CSR       Gig 0/0
```
Field mapping (LLDP):
- Device ID → remote_node
- Local Intf → local_port (normalize)
- Port ID → remote_port (normalize)

Field mapping (CDP):
- Device ID → remote_node
- Local Intrfce → local_port (normalize)
- Port ID → remote_port (normalize)

Skip header, capability legend, separator, empty lines.
Output schema: [{"local_port": str, "remote_node": str, "remote_port": str}]

---

### [cisco:routing_table]
Command: `show ip route`
Template:
```
Codes: C - connected, S - static, ...

Gateway of last resort is 10.1.1.2 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 10.1.1.2
C     10.1.1.0/30 is directly connected, GigabitEthernet0/0/1
S     172.16.0.0/16 [1/0] via 10.1.2.6
```
Field mapping:
- Leading code letter(s) → protocol ("S"→"static", "C"→"direct", "O"→"ospf", "R"→"rip")
- prefix/mask → prefix (CIDR)
- via <ip> → next_hop (empty if directly connected)
- connected interface or via interface → interface (normalize)

Output schema: [{"prefix": str, "next_hop": str, "interface": str, "protocol": str}]

---

### [cisco:interface_brief]
Command: `show ip interface brief`
Template:
```
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0/1  10.1.1.1        YES manual up                    up
GigabitEthernet0/0/2  unassigned      YES unset  administratively down  down
GigabitEthernet0/0/3  unassigned      YES unset  down                   down
```
Field mapping:
- Interface → port (normalize)
- IP-Address → ip ("unassigned" → "")
- Status + Protocol:
  - "up" / "up" → "up"
  - "administratively down" → "admin-down"
  - "down" / "down" → "down"

Output schema: [{"port": str, "ip": str, "status": str}]

---

### [cisco:arp_table]
Command: `show arp`
Template:
```
Protocol  Address          Age (min) Hardware Addr   Type   Interface
Internet  10.1.1.2               5  0012.3456.7890  ARPA   GigabitEthernet0/0/1
```
Field mapping:
- Address → ip
- Hardware Addr → mac
- Interface → port (normalize)

Output schema: [{"ip": str, "mac": str, "port": str}]

---

### [h3c:lldp_neighbors]
Command: `display lldp neighbor-information brief`
Template:
```
System capability : B - Bridge, R - Router, ...

Local Interface   Neighbor ID    PortID               TTL
GE1/0/1          R2             GigabitEthernet1/0/0  120
GE1/0/2          R3             GigabitEthernet1/0/1  115
```
Field mapping:
- Local Interface → local_port (normalize)
- Neighbor ID → remote_node
- PortID → remote_port (normalize)

Output schema: [{"local_port": str, "remote_node": str, "remote_port": str}]

---

### [h3c:routing_table]
Command: `display ip routing-table`
Template:
```
Destinations : 5      Routes : 5

Destination/Mask   Proto    Pre  Cost       NextHop       Interface
0.0.0.0/0         Static   60   0          10.1.1.2      GE1/0/0
10.1.1.0/30       Direct   0    0          10.1.1.1      GE1/0/0
```
Field mapping: identical to Huawei routing table format.
Output schema: [{"prefix": str, "next_hop": str, "interface": str, "protocol": str}]

---

### [h3c:interface_brief]
Command: `display interface brief`
Template:
```
Brief information on interfaces in route mode:
Link: ADM - administratively down; Stby - standby
Speed: (a) - auto; Duplex: (a)/A - auto; (H) - half; (F) - full

Interface          Link  Speed   Duplex   Type   PVID Description
GE1/0/0            UP    1G      (a)F     RJ45   1
GE1/0/1            ADM   auto    (a)A     RJ45   1
GE1/0/2            DOWN  auto    (a)A     RJ45   1
```
Field mapping:
- Interface → port (normalize)
- Link:
  - "UP" → "up"
  - "ADM" → "admin-down"
  - "DOWN" → "down"
- IP address if present → ip, else ""

Output schema: [{"port": str, "ip": str, "status": str}]

---

### [h3c:arp_table]
Command: `display arp`
Template:
```
  IP Address      MAC Address    VLAN  Interface     Aging Type
  10.1.1.2        0012-3456-7890 N/A   GE1/0/0       20    D
```
Field mapping:
- IP Address → ip
- MAC Address → mac
- Interface → port (normalize)

Output schema: [{"ip": str, "mac": str, "port": str}]
"""


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

TRACK_A_RETRIEVAL_SYSTEM = """You are a data retrieval agent.
Your ONLY job is to call the available tools to fetch raw data for the scenario.
Do NOT perform any analysis. Do NOT output reasoning. Call the tools and return.
"""

TRACK_A_ANALYSIS_SYSTEM = f"""{TRACK_A_SKILL}

## Forensic Report Interpretation Guide

A deterministic forensic analysis tool has already run on the raw 5G drive-test data.
Its report uses the following ROOT CAUSE labels — learn what each implies for option selection:

| Label            | Root cause                                       | Typical fix category                        |
|------------------|--------------------------------------------------|---------------------------------------------|
| [SPEED]          | UE speed > 40 km/h → Doppler / HO instability   | Mobility/HO parameter tuning                |
| [RESOURCE]       | DL RBs < 160 → resource starvation              | Check PDCCH config or transmission issues   |
| [TILT]           | Beam geometry mismatch (under/overshoot)         | Tilt adjustment for the serving cell        |
| [DISTANCE]       | UE > 1 km from site → coverage overshoot        | Power / azimuth adjustment or new neighbor  |
| [HANDOVER]       | Multiple PCIs during low-TP → ping-pong / miss  | Add missing neighbor relationship           |
| [BETTER_NEIGHBOR]| Neighbor RSRP > serving RSRP → wrong cell       | A3 threshold / HO parameter or add neighbor |
| [COLOCATION]     | Interference from co-/non-colocated cell         | Power reduction or DMRS/PCI planning        |
| [MOD30]          | DMRS collision (serving PCI % 30 == nbr PCI % 30)| Frequency plan / PCI re-assignment          |

Use the FAIL verdicts in the report to identify active root causes, then match them to the
specific cell/action described in the Candidate Options.

CRITICAL OUTPUT RULES:
- Think step by step, referencing evidence from the Forensic Report.
- End your response with a line: ANSWER: <options in ascending order, pipe-separated>
- The ANSWER line MUST appear AFTER any reasoning — never inside <think> blocks.
"""

TRACK_B_DECOMPOSE_SYSTEM = """You are a task decomposition agent for IP network troubleshooting.

Given a question about a network scenario, extract a structured JSON object with EXACTLY these fields:
{
  "task_type": "TOPOLOGY_RESTORE" | "PATH_QUERY" | "FAULT_DIAGNOSIS",
  "target_node": "<primary node to investigate>",
  "extra_context": {
    "candidate_nodes": [...],     // for TOPOLOGY_RESTORE: all nodes in the scenario
    "source_node": "...",         // for PATH_QUERY: where the path starts
    "destination_ip": "...",      // for PATH_QUERY: destination IP or prefix
    "faulty_node": "..."          // for FAULT_DIAGNOSIS: the suspected faulty node
  }
}

Output ONLY valid JSON. No explanation, no markdown fences, no <think> blocks.
"""

TRACK_B_PARSER_SYSTEM = """You are a CLI output parser agent.
You extract structured data from network device CLI output.
Output ONLY a valid JSON array matching the schema provided. No explanation, no markdown, no <think> blocks.
"""

TRACK_B_REASONING_SYSTEM = """You are an expert IP network engineer with 15 years of multi-vendor experience.

You will receive pre-computed structured facts (topology, routing, interfaces, faults).
Your job is to produce the final answer in the exact required format.

CRITICAL RULES:
- Use ONLY the structured facts provided — never invent links or routes.
- Think step by step in your reasoning, then output a line:
  ANSWER: <your answer in the exact format>
- The ANSWER line must use the exact format for the task type (as detailed in your rule instructions).
- The ANSWER line MUST appear AFTER any reasoning — never inside a <think>...</think> block.
"""


# ---------------------------------------------------------------------------
# Prompt Builder Functions
# ---------------------------------------------------------------------------


def build_track_a_analysis_prompt(
    features: Dict[str, Any],
    rag_context: str,
    options: Dict[str, str],
    tag: str,
) -> str:
    """Assemble the human message for the Track A Analysis Agent.

    Parameters
    ----------
    features : dict
        Pre-computed numeric/boolean feature dict from feature_extraction_node.
        May include ``forensic_report`` key produced by NetworkForensicAnalyzer.
    rag_context : str
        Formatted few-shot examples string from TabularRAG.format_context().
    options : dict
        Candidate options, e.g. {"C1": "Increase TX power", ...}.
    tag : str
        "single-answer" or "multiple-answer".
    """
    forensic_report = features.get("forensic_report", "")
    # Build a clean features summary without the long forensic_report string
    summary_features = {k: v for k, v in features.items() if k != "forensic_report"}

    options_block = "\n".join(f"  {k}: {v}" for k, v in sorted(options.items()))
    tag_instruction = (
        "Select EXACTLY ONE option."
        if "single" in tag
        else "Select EXACTLY 2 or EXACTLY 4 options (never 1, 3, or more than 4), pipe-separated, ascending order."
    )

    forensic_section = (
        f"\n## Deterministic Forensic Report\n{forensic_report}"
        if forensic_report
        else ""
    )

    return f"""## Scenario Features (Summary)
{summary_features}{forensic_section}

## Similar Past Scenarios (Few-Shot Examples)
{rag_context if rag_context else "(none available)"}

## Candidate Options
{options_block}

## Task
{tag_instruction}
Use the Forensic Report above to identify the root cause(s), then map each root cause to the SPECIFIC candidate option(s) that best address it.
The Forensic Report uses descriptive labels (e.g. [SPEED], [TILT], [BETTER_NEIGHBOR], [MOD30]) — these are ROOT CAUSE indicators, NOT option IDs.
Your final ANSWER must reference the option IDs (C1, C2, …) from the Candidate Options list above.
"""


def get_parser_skill_section(vendor: str, command_type: str) -> str:
    """Return the single VENDOR_PARSER_SKILL section for (vendor, command_type).

    Searches VENDOR_PARSER_SKILL for the matching section header
    ``[vendor:command_type]`` and returns only that section's text.

    Parameters
    ----------
    vendor : str
        One of: "huawei", "cisco", "h3c" (case-insensitive).
    command_type : str
        One of: "lldp_neighbors", "routing_table", "interface_brief", "arp_table".

    Returns
    -------
    str
        The matching section text, or empty string if not found.
    """
    vendor_lc = vendor.lower()
    cmd_lc = command_type.lower()
    section_header = f"[{vendor_lc}:{cmd_lc}]"

    lines = VENDOR_PARSER_SKILL.splitlines()
    in_section = False
    section_lines: List[str] = []

    for line in lines:
        if line.strip().startswith("###") and section_header in line:
            in_section = True
            section_lines = [line]
            continue
        if in_section:
            # Stop at next ### section header
            if line.strip().startswith("###") and "[" in line and in_section:
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def build_parser_prompt(
    raw_output: str,
    vendor: str,
    command_type: str,
) -> str:
    """Assemble the human message for the ParserAgent.

    Injects only the relevant VENDOR_PARSER_SKILL section (not the full skill).

    Parameters
    ----------
    raw_output : str
        Raw CLI text returned by the Track B API.
    vendor : str
        Device vendor (huawei / cisco / h3c).
    command_type : str
        Command category (lldp_neighbors / routing_table / interface_brief / arp_table).
    """
    skill_section = get_parser_skill_section(vendor, command_type)
    return f"""## Parser Skill Section
{skill_section}

## Raw CLI Output
```
{raw_output}
```

Extract ALL data rows from the CLI output above and return them as a JSON array matching the schema defined in the skill section.
Output ONLY the JSON array. No explanation, no markdown fences.
"""


def build_track_b_reasoning_prompt(
    question: str,
    task_type: str,
    topology: Dict[str, Any],
    routing: List[Dict[str, Any]],
    interfaces: List[Dict[str, Any]],
    faults: List[Dict[str, Any]],
    computed_path: List[str] | None = None,
    computed_topology: Dict[str, Any] | None = None,
) -> str:
    """Assemble the human message for the Track B Reasoning Agent.

    Parameters
    ----------
    question : str
        Original question text.
    task_type : str
        One of TOPOLOGY_RESTORE, PATH_QUERY, FAULT_DIAGNOSIS.
    topology : dict
        Adjacency dict from build_topology_graph().
    routing : list
        Routing fact list from parse_node.
    interfaces : list
        Interface fact list from parse_node.
    faults : list
        Fault candidate list from detect_faults().
    computed_path : list, optional
        Ordered hop list from trace_path() if available.
    computed_topology : dict, optional
        Full topology adjacency dict after reconciliation.
    """
    import json

    path_block = ""
    if computed_path:
        path_block = f"\n## Computed Path\n{' -> '.join(computed_path)}\n"

    topo_block = ""
    if computed_topology:
        topo_block = f"\n## Computed Topology (adjacency)\n{json.dumps(computed_topology, indent=2)}\n"

    skills = _load_track_b_skills(task_type)

    return f"""## Domain Rules and Answer Format
{skills}

## Question
{question}

## Task Type
{task_type}

## Topology Facts (LLDP)
{json.dumps(topology, indent=2)}
{topo_block}
## Routing Facts
{json.dumps(routing, indent=2)}

## Interface Facts
{json.dumps(interfaces, indent=2)}

## Detected Faults
{json.dumps(faults, indent=2)}
{path_block}
Analyze the structured facts above and produce the final answer in the exact format for {task_type}.
End your response with: ANSWER: <answer>
"""
