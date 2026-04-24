## TRACK B SKILL — TOPOLOGY RESTORE

Your goal is to faithfully reconstruct the physical Layer 2 topology for the target node based ONLY on confirmed evidence. Do NOT guess or hallucinate connections. LLDP and ARP tables form the bedrock of this evidence.

### Link Discovery Priority
1. **LLDP neighbor table** is the primary source for physical topology (Layer 2 adjacency).
2. **ARP table** OVERRIDES LLDP when port information conflicts! Per competition rules, if LLDP says a neighbor is on `GE1/0/0` but ARP resolves the remote node's IP on `Eth1/0/1`, you MUST use the ARP port. Address resolution protocols indicate actual forwardable links.
3. **Interface description** is the lowest priority. Use it ONLY when both LLDP and ARP are completely absent or silent. 

### Interface Status Semantics
| PHY / Protocol | Meaning       | Status field  | Rule |
|----------------|---------------|---------------|------|
| up / up        | Fully up      | up            | Include this link if valid. |
| *down / down   | Admin-down    | admin-down    | Do NOT include admin-down links in restoration profiles unless specifically requested; they are administrative faults, not active links. |
| down / down    | Physical down | down          | Ignore physical down links. |

### Canonical Output Format (TOPOLOGY_RESTORE)
Output exactly one link per line formatting strictly as:
  `LocalNode(LocalPort)->RemoteNode(RemotePort)`

**CRITICAL: Output canonical short port names!**
- GigabitEthernet -> GE (e.g. GE1/0/1)
- Ten-GigabitEthernet -> XGE (e.g. XGE1/0/1)
- Ethernet -> Eth (e.g. Eth1/0/1)

*Example Output*:
NodeA(GE1/0/1)->NodeB(GE0/0/1)
NodeA(Eth1/0/2)->NodeC(Eth0/0/1)

### Chain of Thought Heuristic
1. Gather LLDP table for the target node. Write down all Remote Node to Local Port mappings.
2. Check ARP instances for the target node. For all IPs associated with Remote Nodes, check what port the ARP entry resolves to.
3. If LLDP Port != ARP Port, UPDATE the mapping to use the ARP Port.
4. Convert all ports to canonical short names.
5. Format the output string exactly.
