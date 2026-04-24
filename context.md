# Telco Troubleshooting Agentic Challenge — Context

## 1. Competition Overview

**Host:** Zindi Africa in partnership with ITU AI for Good  
**Prize pool:** €40,000 EUR  
**URL:** https://zindi.africa/competitions/telco-troubleshooting-agentic-challenge  
**Data source (public):** https://huggingface.co/datasets/netop/Telco-Troubleshooting-Agentic-Challenge  
**License:** CC-BY SA 4.0

The challenge asks participants to build intelligent AI agents capable of diagnosing and resolving faults in telecommunications networks — both wireless (5G/LTE) and IP networks. Agents must call domain-specific tool APIs exposed by a simulated **Agent Tool Server** to gather information and produce answers.

**Base model (mandatory):** `Qwen3.5-35B-A3B` — participants may fine-tune (LoRA, full fine-tuning) but may not swap it for a different architecture or parameter scale.

---

## 2. Competition Structure

### Phases

| Phase | Name | Dates | Purpose | Key Deliverable |
|-------|------|-------|---------|-----------------|
| **Phase 1** | Open Practice | 3 Apr – 4 May 2026 | Debug agent, familiarise with API | `result.csv` (unlimited submissions) |
| **Phase 2** | Elimination Round | 4 May – 18 May 2026 | Select top-30 per track | `result.csv` (max 3 submissions) |
| **Phase 3** | Final Round | 18 May – 29 May 2026 | Final ranking | Zip (code + fine-tuned weights), 1 submission |

### Tracks

| Track | Domain | Network Type | Task Style |
|-------|--------|--------------|------------|
| **Track A** | Wireless network troubleshooting | 5G/LTE drive test | Multiple-choice (single or multi-answer) |
| **Track B** | IP network troubleshooting | Multi-vendor IP networks | Open-ended (free-form text) |

> A participant or team can only win in one track.

---

## 3. Data Description

### Track A — Wireless Network

Track A questions are based on **5G network drive test data**. Each question presents a realistic scenario (e.g., throughput degradation, handover failure, interference) and asks the agent to select the correct optimisation action(s) from a list of candidate options (C1, C2, …, Cn).

**Question types:**
- `single-answer` — choose exactly one option, e.g., `C8`
- `multiple-answer` — choose 2–4 options, e.g., `C5|C9|C11`

**Typical topics:**
- Transmission power adjustment
- Antenna tilt / azimuth modification
- Handover threshold tuning (A3 offset, RSRP thresholds)
- Neighbour relationship addition
- Physical channel parameter changes (e.g., PDCCH symbol count)
- Transmission / server issue identification

**Dataset scale:**

| Phase | Split | Size |
|-------|-------|------|
| Phase 1 | Train (with answers) | 2,000 questions |
| Phase 1 | Test (no answers) | 500 questions |
| Phase 2 | Test (no answers) | 500 questions |
| Phase 3 | Private test | 500 questions |

---

### Track B — IP Network

Track B questions require the agent to interact with a **simulated multi-vendor CLI environment** (Huawei / Cisco / H3C devices) to answer open-ended questions about network topology, routing, and fault diagnosis.

**Question types (open-ended):**
- **Topology reconstruction** — identify all UP links on a given node  
  *Format:* `LocalNode(LocalPort)->RemoteNode(RemotePort)`, one link per line
- **Path query** — find the routing path between two network elements  
  *Format:* `NodeA->NodeB->NodeC` on a single line
- **Fault localisation** — diagnose the root cause of a reachability failure

**Network environments per phase:**

| Phase | Scenario | Nodes | Protocols | Vendors |
|-------|----------|-------|-----------|---------|
| Phase 1 | Financial network + Cloud computing network | 32 + 22 | LLDP, OSPF, VXLAN | Multi-vendor |
| Phase 2 | Campus network | 40 | VLAN, VRRP, MP-BGP | Multi-vendor |
| Phase 3 | Financial network (new data) | 64 | VXLAN, EVPN, SRv6, ISIS, BGP | Multi-vendor |

**Dataset scale:**

| Phase | Questions |
|-------|-----------|
| Phase 1 | 50 |
| Phase 2 | 100 (released in batches of 20 every 3 days) |
| Phase 3 | 70 |

---

## 4. Data Organisation

```
data/
└── raw/
    ├── submission/
    │   └── Phase_1/
    │       ├── result.csv            # Example output produced by an agent
    │       └── submission_example.csv
    │
    ├── Track A/
    │   ├── README.md                 # Full Track A specification
    │   ├── server.py                 # Agent Tool Server (tools & simulator, read-only)
    │   ├── main.py                   # Example mock agent / runner
    │   ├── utils.py                  # Helper functions
    │   ├── requirements.txt
    │   ├── _types.py
    │   ├── logger.py
    │   ├── data/
    │   │   └── Phase_1/
    │   │       ├── train.json        # 2,000 questions WITH answers (labelled)
    │   │       └── test.json         # 500 questions WITHOUT answers
    │   └── examples/
    │       └── traces.json           # Example agent reasoning traces
    │
    └── Track B/
        ├── README.md                 # Full Track B specification
        ├── server.py                 # Agent Tool Server (CLI simulator)
        ├── requirements.txt
        ├── question_limits_config.json
        ├── data/
        │   └── Phase_1/
        │       └── test.json         # 50 open-ended questions WITHOUT answers
        ├── examples/
        │   └── traces.json           # Example agent reasoning traces
        └── agent/                    # Example agent skeleton
            ├── evaluate_openclaw.py
            ├── evaluate_openclaw_guideline.md
            ├── requirements.txt
            ├── openclaw_config/
            │   ├── AGENTS.md
            │   ├── IDENTITY.md
            │   ├── SOUL.md
            │   ├── TOOLS.md
            │   └── USER.md
            └── skills/
                ├── adv_tunnel/SKILL.md
                ├── infra_maintenance/SKILL.md
                ├── l2_link/SKILL.md
                └── l3_route/SKILL.md
```

---

## 5. Data File Formats

### Track A — `train.json` / `test.json`

Each file is a JSON array. Every element is a **scenario object**:

```json
{
  "scenario_id": "08e221e5-3ed8-42ed-b7b3-0fd9dfd8d99e",   // UUID, used as row ID in result.csv
  "tag": "multiple-answer",                                  // "single-answer" | "multiple-answer"
  "task": {
    "description": "Analyze 5G network drive test data...", // Natural-language prompt sent to the agent
    "options": [
      { "id": "C1",  "label": "Add neighbor relationship between ..." },
      { "id": "C2",  "label": "Decrease transmission power for ..." },
      ...
    ]
  },
  "answer": "C8|C11"   // Present only in train.json, absent in test.json
}
```

**Key fields:**

| Field | Type | Description |
|-------|------|-------------|
| `scenario_id` | string (UUID) | Unique identifier — used as the `ID` column in submission |
| `tag` | string | `"single-answer"` or `"multiple-answer"` |
| `task.description` | string | Full task prompt including formatting instructions |
| `task.options` | array | Candidate actions (C1…Cn), each with `id` and `label` |
| `answer` | string | Ground-truth answer(s) separated by `\|`, sorted ascending — **train only** |

---

### Track B — `test.json`

Each file is a JSON array. Every element is a **scenario object**:

```json
{
  "scenario_id": "535afb0d-fa81-419b-9bcc-b456d032df5d",  // UUID
  "task": {
    "id": 1,                                               // Sequential integer within the file
    "question": "The link planning data of Gamma-Aegis-01 has been deleted..."
  }
}
```

**Key fields:**

| Field | Type | Description |
|-------|------|-------------|
| `scenario_id` | string (UUID) | Unique identifier — used as the `ID` column in submission |
| `task.id` | integer | Sequential question number within the dataset |
| `task.question` | string | Open-ended question + strict output format instructions |

Track B has **no `answer` field** in any released file (no labelled training set). Agents must solve problems purely by interacting with the CLI tool server.

---

### Submission — `result.csv`

```
ID,Track A,Track B
80e3aa96-815d-4683-980c-16db42eab0ef,C8|C11,
535afb0d-fa81-419b-9bcc-b456d032df5d,,Gamma-Aegis-01(Eth1/0/1)->Gamma-Portal-01(GE0/0/1)
```

- **One row per question** across both tracks in a single file.
- Leave the column blank if the question belongs to the other track or you are not competing in it.
- `Track A` answers: option IDs separated by `|` in ascending order (e.g., `C5|C9|C11`).
- `Track B` answers: free-form text matching the exact format specified in the question.

---

## 6. Server Architecture & Tools

### Track A — Agent Tool Server

The server exposes simulation interfaces for wireless network scenarios. Agents call it via HTTP to retrieve KPIs, drive-test logs, neighbour lists, configuration parameters, etc., then reason over the data to pick the correct option(s).

```
server.py  (tools & simulator)  ←  main.py  (agent)
```

Agents call `server.py` → gather data → produce answer → write `result.csv`.

### Track B — CLI Simulator

The server simulates the CLI of multi-vendor devices. Agents issue CLI commands and parse the output to reconstruct topology or diagnose faults.

**API endpoint:**
```
POST /api/agent/execute
Authorization: Bearer <token>
Content-Type: application/json

{
  "device_name": "BoardLeaf1",
  "command": "display ip routing-table"
}
```

**Supported vendors:** Huawei, Cisco, H3C  
**Supported protocols:** OSPF, BGP, MP-BGP, VXLAN, EVPN, SRv6, ISIS, VLAN, VRRP, LLDP  
**Rate limits (Phase 1):** 1,000 API calls / participant / day; max 2 concurrent problems  
**Tool call rule:** sequential within a single problem (no parallel calls per problem)

**Cloud server endpoints:**
- Hong Kong & others: `124.71.227.61`
- China: `120.46.145.77`

---

## 7. Evaluation

### Track A

$$\text{score} = \text{accuracy} \times \text{discount}$$

$$\text{accuracy} = \frac{|\text{answers} \cap \text{ground truth}|}{|\text{answers} \cup \text{ground truth}|}$$

(Intersection over Union — partial credit for partial overlap.)

### Track B

Binary: answer is correct only if it exactly matches the ground truth.  
Phase 2 secondary metric: for equal accuracy scores, fewer API calls ranks higher.

### Time Discount (Phase 3 only)

| Answering time | Discount |
|----------------|----------|
| < 5 minutes | 100% |
| 5 – 10 minutes | 80% |
| 10 – 15 minutes | 60% |
| > 15 minutes | 0% |

---

## 8. Key Rules & Constraints

- **Base model:** `Qwen3.5-35B-A3B` — mandatory, no substitution allowed.
- Fine-tuning is permitted (LoRA, full fine-tuning).
- Only open-source tools and packages.
- Max team size: 4.
- A participant/team can only win in one track.
- Phase 3: top-30 per track advance; agent code + fine-tuned weights must be submitted.
- Code review for top-30 upon challenge close (48-hour window).
