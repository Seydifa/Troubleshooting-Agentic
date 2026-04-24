## TRACK B SKILL — PATH QUERY

Your goal is to trace the exact route that IP packets will take from a Source Node to a Destination IP/Node across the network. 

### Routing Mechanics & Longest Prefix Match
To determine the next hop for a given destination IP:
1. Examine the routing table of the current node.
2. Filter for all routes that contain the destination IP.
3. Identify the **Longest Prefix Match** (the route with the highest subnet mask number, e.g. `/32` beats `/24`).
4. If multiple routes share the same prefix length, choose the one with the lowest administrative distance or cost (Protocol specific: Connected -> OSPF -> BGP etc).
5. The chosen route points to a Next-Hop IP. Use the ARP / Interface description tables to determine which Node corresponds to that Next-Hop IP.
6. Check if the outgoing interface is strictly `up`/`up`. If it is `admin-down` or `down`, the packet is dropped at this node, terminating the path trace.
7. Repeat this process from the newly reached Next-Hop Node until you reach the destination.

### Trace Limitations & Special cases
- **VRF / Network Instances**: If an interface is bound to a VPN instance, you must query the routing table for that specific VPN instance, not the global table.
- **Blackhole Routing**: If the chosen route explicitly points to a null0 or blackhole interface, traffic is dropped.
- **Loop Detection**: If you arrive at a node you have already visited during this immediate trace, a routing loop exists, and the packet circles endlessly.

### Exact Output Format
Output a single line, with no whitespace around the arrows linking the nodes.
  `NodeA->NodeB->NodeC`

Example:
If node NodeX routes to NodeY, and NodeY routes directly to NodeZ, output:
NodeX->NodeY->NodeZ
