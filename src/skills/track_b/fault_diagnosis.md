## TRACK B SKILL — FAULT DIAGNOSIS

You are an expert at identifying root causes of network reachability issues spanning multiple nodes. A reachability failure can be caused by physical link damage, administrative disabled ports, misconfigured routes, blackholes, or loops.

### Diagnosing Strategy & Fault Categories
The evaluation system recognizes exactly two major output categories of faults: Routing faults and Port faults. You must map your observed evidence directly to one of the allowed categories.

**Output Rule**: Each line represents one fault. Do not leave blank lines in between. Semicolon-separated.

### Port Faults
Format: `fault_node;fault_port;fault_reason`

Allowed `fault_reason` options:
(1) `shutdown`
(2) `interface IP error`
(3) `traffic congestion on port bandwidth`
(4) `MAC address configuration error`
(5) `VPN configuration missing`
(6) `OSPF configuration error`
(7) `MTU value configuration error`
(8) `host information collection function missing`

*Heuristics:*
- If `display interface brief` shows `admin-down` / `*down` / `ADM`, the fault reason is `shutdown`.
- If `display interface brief` shows a physical failure `down` / `down` on an unexpected port mapping, it could be `shutdown` if another port was intended, or a deeper config error.
- Check MTU mismatches if OSPF neighbour states are stuck in `ExStart/Exchange`.

### Routing Faults
Format: `fault_node;destination_IP;fault_reason`

Allowed `fault_reason` options:
(1) `blackhole route`
(2) `missing static route`
(3) `static route error`
(4) `ARP configuration error`
(5) `routing loop`
(6) `BGP configuration error`
(7) `OSPF configuration error`
(8) `loopback IP configuration conflict`
(9) `VXLAN configuration error`
(10) `L3VPN configuration error`
(11) `L2VPN configuration error`
(12) `IS-IS configuration error`
(13) `SRV6-Policy tunnel planning error`

*Heuristics:*
- **missing static route**: If the routing table of a node along the expected path simply lacks any route (or default route) covering the destination IP.
- **blackhole route**: If the static route exists but is pointed to a Null0 interface, OR if the interface it points to is offline preventing traffic egress without withdrawing the route.
- **routing loop**: If NodeA routes prefix X to NodeB, and NodeB routes prefix X back to NodeA.
- **ARP configuration error**: If the route points to an interface, but traffic fails, check ARP. If ARP is incomplete or explicitly resolving manually to a wrong MAC or mismatched Subnet Mask (`interface IP error`).

### Root Cause Selection
Always trace the path from Source to Destination hop-by-hop.
1. The LAST NODE that successfully routes the packet towards the destination (but where the packet fails to leave or is sent wrong) is the `fault_node`.
2. Identify exactly why the packet died at that node and map it to exactly ONE of the fault reasons above.
3. If there are multiple faults, output each on a new line.

*Examples:*
Beta-Axis-01;192.168.1.1;blackhole route
Alpha-Center-02;192.168.1.2;missing static route
Beta-Portal-01;GE1/0/1;shutdown
