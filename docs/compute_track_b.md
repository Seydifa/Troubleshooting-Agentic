# compute_track_b — Graph & Routing Computation Tools

**Source:** `src/tools/compute_track_b.py`

## Purpose
Pure Python computation layer for Track B. All graph traversal, path finding, ARP reconciliation, and fault detection happens here — no LLM, no network calls.

## Functions

### Topology
| Function | Description |
|----------|-------------|
| `build_topology_graph(lldp_facts)` | Build adjacency dict `{node: [(local_port, remote_node, remote_port)]}` |
| `find_links_for_node(node, graph)` | Find all links involving a node, including reverse lookups (for nodes that can't be queried directly) |
| `format_links(links)` | Format to competition output: `Node(Port)->Node(Port)` per line |

### Routing / Path
| Function | Description |
|----------|-------------|
| `find_next_hop(routing_table, destination_ip)` | Longest-prefix match → best route entry |
| `resolve_next_hop_device(next_hop_ip, ifaces, arp)` | Resolve IP to device name |
| `trace_path(start, destination_ip, routing_tables, interface_tables)` | Hop-by-hop path tracing via routing tables; returns ordered node list |

### Reconciliation
| Function | Description |
|----------|-------------|
| `reconcile_arp_vs_lldp(lldp_links, arp_facts, interface_facts)` | Per competition rules: ARP port overrides LLDP description when they differ |

### Fault Detection
| Function | Description |
|----------|-------------|
| `detect_faults(interface_facts, routing_facts)` | Detect admin-down ports + blackhole routes (static route via down interface) |

## Design Rule
All functions are pure (no side effects, no IO). Input is always structured dicts from the parsers in `parsers_track_b`. Output is always structured dicts or formatted strings — never raw CLI text.

## Dependencies
- `ipaddress` (stdlib), `parsers_track_b`
