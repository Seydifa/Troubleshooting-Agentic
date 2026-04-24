# parsers_track_b — Centralized Parser Layer with LLM Normalization

**Source:** `src/tools/parsers_track_b.py`

## Purpose
Normalize raw CLI output from Huawei / Cisco / H3C devices into canonical JSON structures. Instead of brittle per-vendor regex functions, a **`ParserAgent`** uses a `VENDOR_PARSER_SKILL` to identify the vendor format and extract structured data. This makes the parser resilient to firmware variations, vendor-specific quirks, and edge cases that regex cannot handle.

---

## Architecture

```
Raw CLI output  +  vendor tag  (always present in API response)
       │
       ▼
[VendorContextBuilder]          ← pure Python (no LLM)
  - reads vendor tag from API response field
  - maps command_type from the command string
  - selects the matching section of VENDOR_PARSER_SKILL
  - returns: {vendor, command_type, skill_section, raw_output}
       │
       ▼
[ParserAgent]                   ← LLM  (small, focused, JSON-only output)
  System prompt: VENDOR_PARSER_SKILL section for this vendor + command
  Human message: raw CLI output
  Output: strict JSON matching the canonical schema for this command type
  • No chain-of-thought — output is JSON only
  • Temperature = 0 for determinism
       │
       ▼
[SchemaValidator]               ← pure Python
  - validates output matches canonical schema
  - normalizes port names via _normalize_port()
  - if invalid → retry ParserAgent once with error feedback
  - if still invalid → return [] (failure sentinel)
```

---

## TrackBClient
Cached HTTP wrapper for `POST /api/agent/execute`. Tracks `budget_used` counter (Phase 1 limit: 1000/day). Returns `(raw_output, vendor, command_type)` tuple.

---

## Canonical Output Schemas

| Command Type | Schema | Notes |
|---|---|---|
| `lldp_neighbors` | `[{"local_port", "remote_node", "remote_port"}]` | Most critical — drives topology |
| `routing_table` | `[{"prefix", "next_hop", "interface", "protocol"}]` | IP prefix in CIDR notation |
| `interface_brief` | `[{"port", "ip", "status"}]` | status: `up`/`down`/`admin-down` |
| `arp_table` | `[{"ip", "mac", "port"}]` | Used for ARP reconciliation fallback |

Schemas are identical regardless of vendor — the `ParserAgent` handles the transformation.

---

## VENDOR_PARSER_SKILL Sections

The skill (defined in `code6_prompts.py`) has one section per `(vendor, command_type)` pair:

| Vendor | Command Types Covered |
|--------|-----------------------|
| Huawei | lldp_neighbors, routing_table, interface_brief, arp_table |
| Cisco  | lldp_neighbors (LLDP + CDP), routing_table, interface_brief, arp_table |
| H3C    | lldp_neighbors, routing_table, interface_brief, arp_table |

Each section contains:
- A representative output template showing the vendor's format
- Field-to-schema mapping (e.g. `"Local Intf" → local_port`)
- Port name normalization rules for that vendor
- Known edge cases (empty tables, error lines to skip)

---

## Port Normalization
`_normalize_port()` is applied by `SchemaValidator` after parsing, ensuring all port names follow the canonical short form regardless of how the LLM extracted them:
```
GigabitEthernet1/0/1       → GE1/0/1
Ten-GigabitEthernet1/0/1   → XGE1/0/1
Ethernet1/0/1              → Eth1/0/1
GigabitEthernet0/0/1       → GE0/0/1
```

---

## Failure Sentinel
All parsers return `[]` on invalid/empty output — never silently return wrong data. The `discovery_node` checks `len(result) == 0` to trigger the ARP fallback method.

---

## Why LLM for Parsing

| Problem | Regex approach | ParserAgent approach |
|---------|---------------|---------------------|
| New vendor added | New function per command type | Add one skill section |
| Firmware variation in output | Regex breaks silently | LLM reads context, still extracts correctly |
| Vendor error lines in output | Must be explicitly filtered | LLM ignores non-data lines by context |
| Port name aliases | Exhaustive mapping table | Covered by skill normalization rules |
| Partial/truncated output | Returns wrong partial data | LLM extracts what is available, flags incomplete |

---

## Dependencies
- `requests`, `re`, `json`, `langchain_ollama`, `langchain_openai`, `state`, `prompts.code6_prompts`
