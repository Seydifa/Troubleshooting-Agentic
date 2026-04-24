# code6_prompts — Centralized System Prompts

**Source:** `src/prompts/code6_prompts.py`

## Purpose
Single source of truth for all agent system prompts and the telecom skill context injected into the fixed 25% of the context window.

## Skill Context (Static, always injected)

### `TRACK_A_SKILL`
Telecom domain rules for 5G wireless:
- A3 handover formula with unit conversion (0.5dB units)
- RSRP/SINR quality thresholds
- Antenna tilt/azimuth/power optimization guidance
- PDCCH symbol interpretation
- Inter-frequency handover threshold rules

### `TRACK_B_SKILLS`
IP network domain rules:
- Link discovery priority: LLDP > ARP reconciliation
- Interface status semantics (admin-down vs physical down)
- Routing fault categories and definitions
- Exact output format rules per task type

### `VENDOR_PARSER_SKILL`
Specialized skill for the `ParserAgent` — the single source of truth for all vendor CLI output formats. Organized as sections per `(vendor, command_type)` pair:

```
[huawei:lldp_neighbors]
  Template: display lldp neighbor brief output format
  Fields: Local Intf → local_port, Neighbor ID → remote_node, PortID → remote_port
  Edge cases: empty table line, header/separator lines to skip

[huawei:routing_table]
  Template: display ip routing-table output format
  Fields: Destination/Mask → prefix, NextHop → next_hop, Interface → interface, Proto → protocol

[huawei:interface_brief]
  Template: display interface brief output format
  Fields: Interface → port, IP Address → ip, PHY/Protocol → status
  Status map: up/up → up, *down/down → admin-down, down/down → down

[huawei:arp_table]
  Template: display arp output format
  Fields: IP Address → ip, MAC Address → mac, Interface → port

[cisco:lldp_neighbors]  (also covers CDP fallback)
  ...
[cisco:routing_table]
  ...
[h3c:lldp_neighbors]
  ...
(all 12 sections follow same structure)
```

Port normalization rules are embedded at the end of this skill: canonical short-form mapping table for all three vendors.

The `ParserAgent` receives only the **relevant section** for the current `(vendor, command_type)` — not the entire skill — to keep the prompt budget minimal.

## System Prompts

| Constant | Agent | Role |
|----------|-------|------|
| `TRACK_A_RETRIEVAL_SYSTEM` | Track A Retrieval Agent | Pure tool-calling, no reasoning |
| `TRACK_A_ANALYSIS_SYSTEM` | Track A Analysis Agent | Expert RF engineer with domain rules embedded |
| `TRACK_B_DECOMPOSE_SYSTEM` | Track B Decomposer Agent | Extracts structured sub-task JSON |
| `TRACK_B_PARSER_SYSTEM` | Track B ParserAgent | JSON-only output, vendor normalization |
| `TRACK_B_REASONING_SYSTEM` | Track B Reasoning Agent | Expert IP network engineer with domain rules embedded |

## Prompt Builder Functions

| Function | Description |
|----------|-------------|
| `build_track_a_analysis_prompt(features, rag_context, options, tag)` | Assembles the full human message for Analysis Agent |
| `get_parser_skill_section(vendor, command_type)` | Returns the single relevant `VENDOR_PARSER_SKILL` section — not the full skill — to minimize parser prompt size |
| `build_parser_prompt(raw_output, vendor, command_type)` | Assembles the human message for ParserAgent: skill section + raw CLI output + target schema |
| `build_track_b_reasoning_prompt(question, topology, routing, interfaces, faults)` | Assembles the full human message for Reasoning Agent |

## Context Budget Rule
System prompts + skill context = ~25% of model context window. The remaining 75% is for structured facts + few-shot examples + chain-of-thought output.

## Dependencies
None (stdlib only).
