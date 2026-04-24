"""
conftest.py — Shared pytest fixtures.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def sample_scenario_a():
    return {
        "scenario_id": "test-scenario-a-001",
        "task": {
            "description": "Which optimization action should be taken?",
            "options": [
                {"id": "C1", "label": "Increase TX power"},
                {"id": "C2", "label": "Add neighbor relation"},
                {"id": "C3", "label": "Reduce tilt"},
                {"id": "C4", "label": "Change azimuth"},
            ],
        },
        "tag": "single-answer",
        "track": "A",
    }


@pytest.fixture()
def sample_scenario_b():
    return {
        "scenario_id": "test-scenario-b-001",
        "task": {
            "question": "What is the path from R1 to 10.1.2.0/24?",
            "id": 1,
        },
        "track": "B",
    }


@pytest.fixture()
def sample_lldp_facts():
    return [
        {"local_port": "GE1/0/0", "remote_node": "R2", "remote_port": "GE0/0/1"},
        {"local_port": "GE1/0/1", "remote_node": "R3", "remote_port": "GE0/0/0"},
    ]


@pytest.fixture()
def sample_routing_facts():
    return [
        {
            "prefix": "0.0.0.0/0",
            "next_hop": "10.1.1.2",
            "interface": "GE1/0/0",
            "protocol": "static",
        },
        {
            "prefix": "10.1.1.0/30",
            "next_hop": "",
            "interface": "GE1/0/0",
            "protocol": "direct",
        },
        {
            "prefix": "10.1.2.0/24",
            "next_hop": "10.1.1.6",
            "interface": "GE1/0/1",
            "protocol": "static",
        },
    ]


@pytest.fixture()
def sample_interface_facts():
    return [
        {"port": "GE1/0/0", "ip": "10.1.1.1", "status": "up"},
        {"port": "GE1/0/1", "ip": "10.1.1.5", "status": "admin-down"},
        {"port": "GE1/0/2", "ip": "", "status": "down"},
    ]


@pytest.fixture()
def sample_arp_facts():
    return [
        {"ip": "10.1.1.2", "mac": "0012-3456-7890", "port": "GE1/0/0"},
        {"ip": "10.1.1.6", "mac": "0012-3456-aabb", "port": "GE1/0/1"},
    ]
