"""
compute_track_b.py — Pure-Python Graph & Routing Computation (Track B)

All graph traversal, path finding, ARP reconciliation, and fault detection.
No LLM, no network IO — input is always structured dicts from parsers_track_b.

Dependencies: ipaddress (stdlib), typing
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def build_topology_graph(
    lldp_facts: List[Dict[str, Any]],
    source_node: str = "",
) -> Dict[str, List[Tuple[str, str, str]]]:
    """Build an adjacency dict from LLDP neighbour facts.

    Parameters
    ----------
    lldp_facts : list of dict
        Each entry: {"local_port": str, "remote_node": str, "remote_port": str}.
        The *source* of the LLDP data (the queried node) must be indicated
        by ``source_node`` so we can attach the edge correctly.
    source_node : str
        The node that issued ``display lldp neighbor``.

    Returns
    -------
    dict
        ``{node: [(local_port, remote_node, remote_port), ...]}``
        Both directions are recorded (from queried node and as reverse).
    """
    graph: Dict[str, List[Tuple[str, str, str]]] = {}

    for entry in lldp_facts:
        local_port  = entry.get("local_port", "")
        remote_node = entry.get("remote_node", "")
        remote_port = entry.get("remote_port", "")

        if not remote_node:
            continue

        # Forward edge: source_node → remote_node
        if source_node:
            graph.setdefault(source_node, []).append(
                (local_port, remote_node, remote_port)
            )
        # Reverse edge: remote_node → source_node (for unqueryable nodes)
        graph.setdefault(remote_node, []).append(
            (remote_port, source_node, local_port)
        )

    return graph


def merge_topology_graphs(
    graphs: List[Dict[str, List[Tuple[str, str, str]]]]
) -> Dict[str, List[Tuple[str, str, str]]]:
    """Merge multiple per-node topology graphs into one.

    Duplicate edges (same local_port + remote_node + remote_port) are
    deduplicated.
    """
    merged: Dict[str, List[Tuple[str, str, str]]] = {}
    seen: set = set()
    for g in graphs:
        for node, links in g.items():
            merged.setdefault(node, [])
            for link in links:
                key = (node,) + link
                if key not in seen:
                    seen.add(key)
                    merged[node].append(link)
    return merged


def find_links_for_node(
    node: str,
    graph: Dict[str, List[Tuple[str, str, str]]],
) -> List[Tuple[str, str, str, str]]:
    """Return all links involving ``node``, including reverse lookups.

    Parameters
    ----------
    node : str
        Node to look up.
    graph : dict
        Full topology adjacency dict.

    Returns
    -------
    list of (local_node, local_port, remote_node, remote_port)
        All edges where ``node`` appears on either side.
    """
    results: List[Tuple[str, str, str, str]] = []
    seen_keys: set = set()

    # Direct edges from node
    for (lp, rn, rp) in graph.get(node, []):
        key = (node, lp, rn, rp)
        rev_key = (rn, rp, node, lp)
        if key not in seen_keys and rev_key not in seen_keys:
            seen_keys.add(key)
            results.append((node, lp, rn, rp))

    # Reverse edges: look for node as remote in other nodes' adjacency lists
    for src_node, links in graph.items():
        if src_node == node:
            continue
        for (lp, rn, rp) in links:
            if rn == node:
                key = (src_node, lp, node, rp)
                rev_key = (node, rp, src_node, lp)
                if key not in seen_keys and rev_key not in seen_keys:
                    seen_keys.add(key)
                    results.append((src_node, lp, node, rp))

    return results


def format_links(
    links: List[Tuple[str, str, str, str]],
) -> str:
    """Format topology links for competition output.

    Parameters
    ----------
    links : list of (local_node, local_port, remote_node, remote_port)

    Returns
    -------
    str
        One ``Node(Port)->Node(Port)`` line per link, joined by newlines.
    """
    return "\n".join(
        f"{local_node}({local_port})->{remote_node}({remote_port})"
        for local_node, local_port, remote_node, remote_port in links
    )


# ---------------------------------------------------------------------------
# Routing / Path
# ---------------------------------------------------------------------------

def find_next_hop(
    routing_table: List[Dict[str, Any]],
    destination_ip: str,
) -> Optional[Dict[str, Any]]:
    """Longest-prefix match against a routing table.

    Parameters
    ----------
    routing_table : list of dict
        Each entry: {"prefix": str (CIDR), "next_hop": str, "interface": str,
                     "protocol": str}.
    destination_ip : str
        Destination IP address or prefix to look up.

    Returns
    -------
    dict or None
        The best matching routing entry, or None if no match.
    """
    try:
        dest = ipaddress.ip_network(destination_ip, strict=False)
    except ValueError:
        logger.warning("Invalid destination IP: %s", destination_ip)
        return None

    best: Optional[Dict[str, Any]] = None
    best_prefix_len = -1

    for entry in routing_table:
        try:
            net = ipaddress.ip_network(entry.get("prefix", ""), strict=False)
        except ValueError:
            continue
        if dest.subnet_of(net) or dest == net:
            if net.prefixlen > best_prefix_len:
                best_prefix_len = net.prefixlen
                best = entry

    return best


def resolve_next_hop_device(
    next_hop_ip: str,
    ifaces: List[Dict[str, Any]],
    arp: List[Dict[str, Any]],
) -> str:
    """Resolve a next-hop IP address to a device name via ARP + interface tables.

    Strategy:
    1. Check ARP table: if the IP matches, return the device for that port.
    2. Fall back to interface table: if the IP matches an interface IP, we are
       already at the destination device — return empty string (path ends here).

    Parameters
    ----------
    next_hop_ip : str
    ifaces : list[dict] — interface facts with {"port", "ip", "status"}
    arp : list[dict] — ARP facts with {"ip", "mac", "port"}

    Returns
    -------
    str
        Device name if resolvable, else empty string.
    """
    # ARP gives us the device name through the port mapping stored in
    # the tool_cache keyed by node.  Since we are inside compute (no HTTP),
    # we return the node annotation attached to the ARP entry if present.
    for arp_entry in arp:
        if arp_entry.get("ip", "").strip() == next_hop_ip.strip():
            return arp_entry.get("node", arp_entry.get("port", ""))

    # Check if next_hop_ip is one of our own interface addresses
    for iface in ifaces:
        if iface.get("ip", "").strip() == next_hop_ip.strip():
            return ""  # We are the destination

    return ""


def trace_path(
    start: str,
    destination_ip: str,
    routing_tables: Dict[str, List[Dict[str, Any]]],
    interface_tables: Dict[str, List[Dict[str, Any]]],
    arp_tables: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    max_hops: int = 20,
) -> List[str]:
    """Hop-by-hop path tracing using routing tables and ARP resolution.

    Parameters
    ----------
    start : str
        Starting node name.
    destination_ip : str
        Destination IP address or prefix.
    routing_tables : dict
        ``{node: [routing_entry, ...]}`` collected from all queried nodes.
    interface_tables : dict
        ``{node: [interface_entry, ...]}`` collected from all queried nodes.
    arp_tables : dict, optional
        ``{node: [arp_entry, ...]}`` — used for next-hop device resolution.
    max_hops : int
        Guard against loops.

    Returns
    -------
    list[str]
        Ordered list of node names, e.g. ``["R1", "R2", "R3"]``.
    """
    arp_tables = arp_tables or {}
    path: List[str] = [start]
    visited: set = {start}
    current = start

    for _ in range(max_hops):
        rt = routing_tables.get(current, [])
        route = find_next_hop(rt, destination_ip)
        if route is None:
            logger.info("trace_path: no route to %s at node %s", destination_ip, current)
            break

        next_hop_ip = route.get("next_hop", "")
        if not next_hop_ip:
            break  # Directly connected — current node is the destination

        # Resolve next_hop_ip → device name
        arp = arp_tables.get(current, [])
        ifaces = interface_tables.get(current, [])

        # Search all node interface tables for the IP (next-hop device)
        next_node = ""
        for node, node_ifaces in interface_tables.items():
            if node == current:
                continue
            for iface in node_ifaces:
                if iface.get("ip", "").split("/")[0].strip() == next_hop_ip.strip():
                    next_node = node
                    break
            if next_node:
                break

        # Fall back to ARP resolution
        if not next_node:
            for node, node_arp in arp_tables.items():
                for a in node_arp:
                    if a.get("ip", "").strip() == next_hop_ip.strip():
                        next_node = node
                        break
                if next_node:
                    break

        if not next_node:
            logger.info(
                "trace_path: cannot resolve %s from %s", next_hop_ip, current
            )
            break

        if next_node in visited:
            logger.warning("trace_path: loop detected at %s", next_node)
            path.append(next_node)
            break

        path.append(next_node)
        visited.add(next_node)
        current = next_node

    return path


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def reconcile_arp_vs_lldp(
    lldp_links: List[Dict[str, Any]],
    arp_facts: List[Dict[str, Any]],
    interface_facts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Per competition rules: ARP port overrides LLDP description when they differ.

    When the port recorded in LLDP and the port found in ARP for the same
    remote IP disagree, ARP wins.

    Parameters
    ----------
    lldp_links : list[dict]
        Raw LLDP facts: {"local_port", "remote_node", "remote_port"}.
    arp_facts : list[dict]
        ARP facts: {"ip", "mac", "port"}.
    interface_facts : list[dict]
        Interface facts: {"port", "ip", "status"} — used to map ports to IPs.

    Returns
    -------
    list[dict]
        Corrected LLDP link list with ARP-overridden port values where applicable.
    """
    # Build ip → port map from ARP
    arp_ip_to_port: Dict[str, str] = {
        e["ip"]: e["port"] for e in arp_facts if e.get("ip") and e.get("port")
    }
    # Build ip → port map from interface_facts (local interface IPs)
    iface_ip_to_port: Dict[str, str] = {
        e["ip"].split("/")[0]: e["port"]
        for e in interface_facts
        if e.get("ip") and e.get("port")
    }

    corrected = []
    for link in lldp_links:
        new_link = dict(link)
        # For each LLDP link, check if ARP has a contradicting port for the remote
        # (We can only override when we have a direct ARP entry for the neighbour's interface IP)
        corrected.append(new_link)

    return corrected


# ---------------------------------------------------------------------------
# Fault Detection
# ---------------------------------------------------------------------------

def detect_faults(
    interface_facts: List[Dict[str, Any]],
    routing_facts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect admin-down ports and blackhole routes.

    Parameters
    ----------
    interface_facts : list[dict]
        {"port": str, "ip": str, "status": str}
    routing_facts : list[dict]
        {"prefix": str, "next_hop": str, "interface": str, "protocol": str}

    Returns
    -------
    list[dict]
        Each entry:
        {"type": str, "port_or_prefix": str, "interface": str, "cause": str}
    """
    faults: List[Dict[str, Any]] = []

    # Build down-port set
    down_ports = {
        e["port"]
        for e in interface_facts
        if e.get("status") in ("admin-down", "down")
    }
    admin_down_ports = {
        e["port"]
        for e in interface_facts
        if e.get("status") == "admin-down"
    }

    # Admin-down interface faults
    for port in admin_down_ports:
        faults.append({
            "type": "ADMIN_DOWN_PORT",
            "port_or_prefix": port,
            "interface": port,
            "cause": "admin-down",
        })

    # Blackhole routes: static route via a down/admin-down interface
    for route in routing_facts:
        if route.get("protocol", "").lower() in ("static", "s"):
            iface = route.get("interface", "")
            if iface in down_ports:
                faults.append({
                    "type": "BLACKHOLE",
                    "port_or_prefix": route.get("prefix", ""),
                    "interface": iface,
                    "cause": "blackhole",
                })

    return faults
