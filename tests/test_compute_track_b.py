"""
test_compute_track_b.py — Tests for src/tools/compute_track_b.py
(all pure Python — no LLM, no HTTP).
"""

from __future__ import annotations

import pytest

from src.tools.compute_track_b import (
    build_topology_graph,
    detect_faults,
    find_links_for_node,
    find_next_hop,
    format_links,
    merge_topology_graphs,
    reconcile_arp_vs_lldp,
    trace_path,
)


# ---------------------------------------------------------------------------
# build_topology_graph
# ---------------------------------------------------------------------------


class TestBuildTopologyGraph:
    def test_empty_facts(self):
        graph = build_topology_graph([], source_node="R1")
        assert graph == {}

    def test_single_link_creates_both_directions(self, sample_lldp_facts):
        facts = [
            {"local_port": "GE1/0/0", "remote_node": "R2", "remote_port": "GE0/0/1"}
        ]
        graph = build_topology_graph(facts, source_node="R1")
        # Forward: R1 → R2
        assert ("GE1/0/0", "R2", "GE0/0/1") in graph["R1"]
        # Reverse: R2 → R1
        assert ("GE0/0/1", "R1", "GE1/0/0") in graph["R2"]

    def test_no_source_node_only_reverse(self):
        facts = [
            {"local_port": "GE1/0/0", "remote_node": "R2", "remote_port": "GE0/0/1"}
        ]
        graph = build_topology_graph(facts, source_node="")
        assert "R1" not in graph
        assert "R2" in graph

    def test_entry_with_empty_remote_node_skipped(self):
        facts = [{"local_port": "GE1/0/0", "remote_node": "", "remote_port": "GE0/0/1"}]
        graph = build_topology_graph(facts, source_node="R1")
        assert graph == {}

    def test_multiple_links(self, sample_lldp_facts):
        graph = build_topology_graph(sample_lldp_facts, source_node="R1")
        assert len(graph["R1"]) == 2
        assert "R2" in graph
        assert "R3" in graph


# ---------------------------------------------------------------------------
# merge_topology_graphs
# ---------------------------------------------------------------------------


class TestMergeTopologyGraphs:
    def test_empty_list(self):
        assert merge_topology_graphs([]) == {}

    def test_single_graph(self):
        g = {"R1": [("GE1/0/0", "R2", "GE0/0/1")]}
        merged = merge_topology_graphs([g])
        assert merged == g

    def test_deduplication(self):
        link = ("GE1/0/0", "R2", "GE0/0/1")
        g1 = {"R1": [link]}
        g2 = {"R1": [link]}  # duplicate
        merged = merge_topology_graphs([g1, g2])
        assert len(merged["R1"]) == 1

    def test_merges_different_nodes(self):
        g1 = {"R1": [("GE1/0/0", "R2", "GE0/0/1")]}
        g2 = {"R3": [("GE1/0/0", "R4", "GE0/0/0")]}
        merged = merge_topology_graphs([g1, g2])
        assert "R1" in merged
        assert "R3" in merged


# ---------------------------------------------------------------------------
# find_links_for_node
# ---------------------------------------------------------------------------


class TestFindLinksForNode:
    def test_direct_links_returned(self):
        graph = {
            "R1": [("GE1/0/0", "R2", "GE0/0/1")],
        }
        links = find_links_for_node("R1", graph)
        assert len(links) == 1
        assert links[0] == ("R1", "GE1/0/0", "R2", "GE0/0/1")

    def test_reverse_links_found(self):
        graph = {
            "R2": [("GE0/0/1", "R1", "GE1/0/0")],
        }
        links = find_links_for_node("R1", graph)
        assert len(links) == 1
        assert links[0] == ("R2", "GE0/0/1", "R1", "GE1/0/0")

    def test_no_duplicates(self):
        # R1 has a forward edge AND R2 has the reverse — should not double-count
        graph = {
            "R1": [("GE1/0/0", "R2", "GE0/0/1")],
            "R2": [("GE0/0/1", "R1", "GE1/0/0")],
        }
        links = find_links_for_node("R1", graph)
        assert len(links) == 1

    def test_unknown_node_returns_empty(self):
        graph = {"R1": [("GE1/0/0", "R2", "GE0/0/1")]}
        links = find_links_for_node("R99", graph)
        assert links == []


# ---------------------------------------------------------------------------
# format_links
# ---------------------------------------------------------------------------


class TestFormatLinks:
    def test_single_link(self):
        links = [("R1", "GE1/0/0", "R2", "GE0/0/1")]
        result = format_links(links)
        assert result == "R1(GE1/0/0)->R2(GE0/0/1)"

    def test_multiple_links(self):
        links = [
            ("R1", "GE1/0/0", "R2", "GE0/0/1"),
            ("R1", "GE1/0/1", "R3", "GE0/0/0"),
        ]
        result = format_links(links)
        lines = result.splitlines()
        assert len(lines) == 2
        assert "R1(GE1/0/0)->R2(GE0/0/1)" in lines

    def test_empty_links(self):
        assert format_links([]) == ""


# ---------------------------------------------------------------------------
# find_next_hop
# ---------------------------------------------------------------------------


class TestFindNextHop:
    def test_exact_match(self):
        rt = [
            {
                "prefix": "10.1.2.0/24",
                "next_hop": "10.1.1.6",
                "interface": "GE1/0/1",
                "protocol": "static",
            }
        ]
        result = find_next_hop(rt, "10.1.2.5")
        assert result is not None
        assert result["next_hop"] == "10.1.1.6"

    def test_default_route(self):
        rt = [
            {
                "prefix": "0.0.0.0/0",
                "next_hop": "10.1.1.2",
                "interface": "GE1/0/0",
                "protocol": "static",
            }
        ]
        result = find_next_hop(rt, "8.8.8.8")
        assert result is not None
        assert result["next_hop"] == "10.1.1.2"

    def test_longest_prefix_match(self):
        rt = [
            {
                "prefix": "0.0.0.0/0",
                "next_hop": "10.1.1.2",
                "interface": "GE0",
                "protocol": "static",
            },
            {
                "prefix": "10.1.2.0/24",
                "next_hop": "10.1.1.6",
                "interface": "GE1",
                "protocol": "static",
            },
            {
                "prefix": "10.1.2.0/28",
                "next_hop": "10.1.1.9",
                "interface": "GE2",
                "protocol": "static",
            },
        ]
        result = find_next_hop(rt, "10.1.2.5")
        # /28 is more specific than /24
        assert result["interface"] == "GE2"

    def test_no_match(self):
        rt = [
            {
                "prefix": "10.1.2.0/24",
                "next_hop": "10.1.1.6",
                "interface": "GE1",
                "protocol": "static",
            }
        ]
        result = find_next_hop(rt, "192.168.1.1")
        assert result is None

    def test_empty_routing_table(self):
        assert find_next_hop([], "10.1.1.1") is None

    def test_invalid_destination_returns_none(self):
        rt = [
            {
                "prefix": "0.0.0.0/0",
                "next_hop": "10.1.1.2",
                "interface": "GE0",
                "protocol": "static",
            }
        ]
        result = find_next_hop(rt, "not-an-ip")
        assert result is None


# ---------------------------------------------------------------------------
# trace_path
# ---------------------------------------------------------------------------


class TestTracePath:
    def test_simple_two_hop_path(self):
        routing_tables = {
            "R1": [
                {
                    "prefix": "10.1.2.0/24",
                    "next_hop": "10.1.1.6",
                    "interface": "GE1/0/1",
                    "protocol": "static",
                },
            ],
        }
        interface_tables = {
            "R2": [{"port": "GE1/0/0", "ip": "10.1.1.6", "status": "up"}],
        }
        path = trace_path(
            start="R1",
            destination_ip="10.1.2.5",
            routing_tables=routing_tables,
            interface_tables=interface_tables,
        )
        assert path[0] == "R1"
        assert "R2" in path

    def test_no_route_returns_start_only(self):
        path = trace_path(
            start="R1",
            destination_ip="9.9.9.9",
            routing_tables={"R1": []},
            interface_tables={},
        )
        assert path == ["R1"]

    def test_loop_detection(self):
        routing_tables = {
            "R1": [
                {
                    "prefix": "0.0.0.0/0",
                    "next_hop": "10.1.1.2",
                    "interface": "GE0",
                    "protocol": "static",
                }
            ],
            "R2": [
                {
                    "prefix": "0.0.0.0/0",
                    "next_hop": "10.1.1.1",
                    "interface": "GE0",
                    "protocol": "static",
                }
            ],
        }
        interface_tables = {
            "R1": [{"port": "GE0", "ip": "10.1.1.1", "status": "up"}],
            "R2": [{"port": "GE0", "ip": "10.1.1.2", "status": "up"}],
        }
        path = trace_path(
            start="R1",
            destination_ip="8.8.8.8",
            routing_tables=routing_tables,
            interface_tables=interface_tables,
            max_hops=10,
        )
        # Loop should be detected and path terminated
        assert len(path) <= 4  # R1 → R2 → R1 (detected) → stop


# ---------------------------------------------------------------------------
# detect_faults
# ---------------------------------------------------------------------------


class TestDetectFaults:
    def test_admin_down_port_detected(
        self, sample_interface_facts, sample_routing_facts
    ):
        faults = detect_faults(sample_interface_facts, sample_routing_facts)
        types = {f["type"] for f in faults}
        assert "ADMIN_DOWN_PORT" in types

    def test_blackhole_detected(self, sample_interface_facts, sample_routing_facts):
        # GE1/0/1 is admin-down, and there's a static route via GE1/0/1
        faults = detect_faults(sample_interface_facts, sample_routing_facts)
        blackholes = [f for f in faults if f["type"] == "BLACKHOLE"]
        assert len(blackholes) >= 1
        assert blackholes[0]["cause"] == "blackhole"

    def test_no_faults_when_all_up(self):
        ifaces = [{"port": "GE1/0/0", "ip": "10.1.1.1", "status": "up"}]
        routes = [
            {
                "prefix": "0.0.0.0/0",
                "next_hop": "10.1.1.2",
                "interface": "GE1/0/0",
                "protocol": "static",
            }
        ]
        faults = detect_faults(ifaces, routes)
        assert faults == []

    def test_only_admin_down_creates_blackhole(self):
        ifaces = [
            {"port": "GE1/0/0", "ip": "10.1.1.1", "status": "admin-down"},
        ]
        routes = [
            {
                "prefix": "10.0.0.0/8",
                "next_hop": "10.1.1.2",
                "interface": "GE1/0/0",
                "protocol": "static",
            },
        ]
        faults = detect_faults(ifaces, routes)
        blackholes = [f for f in faults if f["type"] == "BLACKHOLE"]
        admin_downs = [f for f in faults if f["type"] == "ADMIN_DOWN_PORT"]
        assert len(blackholes) == 1
        assert len(admin_downs) == 1

    def test_dynamic_route_via_down_port_not_blackhole(self):
        ifaces = [{"port": "GE1/0/0", "ip": "", "status": "admin-down"}]
        routes = [
            {
                "prefix": "10.0.0.0/8",
                "next_hop": "10.1.1.2",
                "interface": "GE1/0/0",
                "protocol": "ospf",
            },
        ]
        faults = detect_faults(ifaces, routes)
        blackholes = [f for f in faults if f["type"] == "BLACKHOLE"]
        assert blackholes == []


# ---------------------------------------------------------------------------
# reconcile_arp_vs_lldp
# ---------------------------------------------------------------------------


class TestReconcileArpVsLldp:
    def test_returns_same_count_as_input(
        self, sample_lldp_facts, sample_arp_facts, sample_interface_facts
    ):
        corrected = reconcile_arp_vs_lldp(
            sample_lldp_facts, sample_arp_facts, sample_interface_facts
        )
        assert len(corrected) == len(sample_lldp_facts)

    def test_passthrough_preserves_fields(self, sample_lldp_facts):
        corrected = reconcile_arp_vs_lldp(sample_lldp_facts, [], [])
        assert corrected[0]["local_port"] == sample_lldp_facts[0]["local_port"]
        assert corrected[0]["remote_node"] == sample_lldp_facts[0]["remote_node"]

    def test_empty_lldp_returns_empty(self):
        assert reconcile_arp_vs_lldp([], [], []) == []
