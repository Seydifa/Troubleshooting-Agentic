## TRACK A SKILL — 5G RF Troubleshooting & Optimization Domain Rules

You are entrusted with optimizing a 5G wireless network based on actual field drive test data. You have access to immense context. Do not jump to trivial conclusions without applying structured, multi-step heuristic reasoning based on causal correlations.

### A3 Handover Formula
The A3 event triggers when the serving cell's RSRP is out-performed by a neighboring cell by a specific margin, prompting a handover.
  `Serving RSRP + A3Offset < Neighbor RSRP - Hysteresis`

Unit conversion: A3Offset and Hysteresis are stored in 0.5 dB units.
  `threshold_db = (IntraFreqHoA3Offset + A3HystDB) * 0.5`

If `serving_rsrp + threshold_db > neighbor_rsrp`, the handover has NOT triggered yet. If the call drops before the handover triggers, you have a LATE_HANDOVER candidate.
`delta_db = neighbor_rsrp - serving_rsrp`

### RSRP Quality Thresholds
| RSRP (dBm)   | Quality     | Interpretation |
|--------------|-------------|----------------|
| > -80        | Excellent   | Strong coverage, unlikely to be coverage limited. |
| -80 to -90   | Good        | Sufficient for most operations. |
| -90 to -100  | Fair        | Nearing cell edge, susceptible to interference. |
| -100 to -110 | Poor        | Dropped calls likely. |
| < -110       | Very poor   | Coverage Hole. |

### SINR Thresholds
| SINR (dB) | Quality     | Interpretation |
|-----------|-------------|----------------|
| > 20      | Excellent   | Perfectly isolated signal. |
| 10 to 20  | Good        | Minor crosstalk. |
| 0 to 10   | Fair        | Heavy degradation, check for overlapping beams (Mod3 interference). |
| < 0       | Interference/Coverage Hole | The signal is drowned out. |

### Causal Decision Tree & Problem Classification
1. **LATE_HANDOVER**: `handover_failure=True` AND `delta_db >= threshold_db`. 
   *Resolution*: Decrease the A3 offset threshold, or increase the power of the target neighbor to trigger the handover sooner.
2. **INTERFERENCE**: `serving_sinr < 0 dB` AND `serving_rsrp > -100 dBm`.
   *Resolution*: Adjust the azimuth or tilt (press down) the interfering neighbor. Do NOT just increase power, as that creates more noise.
3. **COVERAGE_HOLE**: `serving_rsrp < -110 dBm`.
   *Resolution*: Lift the tilt of the serving cell or increase its transmission power.
4. **TX_POWER_ISSUE**: `serving cell max power < reference`.
   *Resolution*: Increase transmission power.
5. **PDCCH_ISSUE**: PDCCH symbol count is non-standard (`PdcchOccupiedSymbolNum` not optimal) or poor utilization.
   *Resolution*: Modify `PdcchOccupiedSymbolNum` to default optimal settings based on load (typically 2SYM).
6. **NEIGHBOR_MISSING**: A physically close and strong neighbor PCI is completely absent in the measurement lists.
   *Resolution*: Add a neighbor relationship. Do NOT guess; verify the PCI exists nearby explicitly.

### RAG Example Handling (CRITICAL)
- **DO NOT blindly copy answer combinations** from the "Similar Past Scenarios".
- Tabular past examples only show historically chosen combinations. Your task is to evaluate each of the *Candidate Options* provided in the current prompt individually. 
- You MUST evaluate each possible solution and select a subset (or one) from all possibilities that specifically fix the current scenario's faults.
- If RAG provides examples such as:
  Example 1: RSRP -84.3... Answer: C1|C15.
  Example 2: RSRP -98.4... Answer: C1|C21.
  Example 3: RSRP -83.2... Answer: C5|C8.
  You must decompose the solutions into the individual diagnostics (e.g., C1, C5, C8, C15, C21). Then, evaluate these options against the current facts and select the exact combination that satisfies your reasoning (e.g., Output: `C1|C8`).

### Answer Format Rules
- Follow the prompt exactly. Do not provide extraneous symbols.
- **Single Answer**: exactly one `Cn` enclosed in boxes if requested (e.g. `C8` or `\\boxed{{C8}}`).
- **Multiple Answers**: pipe-separated, **ascending order** (e.g. `C2|C5|C11|C18` or `\\boxed{{C3|C7}}`).
- NEVER include explanations in the answer field — only the `Cn` codes.
