"""
test_parsers_track_b.py — Tests for src/tools/parsers_track_b.py
(pure-Python helpers; LLM-based ParserAgent is mocked).
"""

from __future__ import annotations

import json

import pytest

from src.tools.parsers_track_b import (
    SchemaValidator,
    TrackBClient,
    _extract_json_list,
    _normalize_port,
)


# ---------------------------------------------------------------------------
# _normalize_port
# ---------------------------------------------------------------------------


class TestNormalizePort:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("GigabitEthernet1/0/1", "GE1/0/1"),
            ("Ten-GigabitEthernet1/0/1", "XGE1/0/1"),
            ("TenGigabitEthernet2/0/0", "XGE2/0/0"),
            ("Ethernet0/0/1", "Eth0/0/1"),
            ("LoopBack0", "Loop0"),
            ("Gi0/0/1", "GE0/0/1"),
            ("GE1/0/1", "GE1/0/1"),  # already canonical
            ("XGE1/0/0", "XGE1/0/0"),  # already canonical
            ("", ""),  # empty passthrough
        ],
    )
    def test_normalization(self, raw, expected):
        assert _normalize_port(raw) == expected

    def test_none_like_empty_string(self):
        assert _normalize_port("") == ""


# ---------------------------------------------------------------------------
# _extract_json_list
# ---------------------------------------------------------------------------


class TestExtractJsonList:
    def test_plain_json_array(self):
        text = '[{"a": 1}, {"b": 2}]'
        result = _extract_json_list(text)
        assert result == [{"a": 1}, {"b": 2}]

    def test_markdown_fenced(self):
        text = '```json\n[{"x": "y"}]\n```'
        result = _extract_json_list(text)
        assert result == [{"x": "y"}]

    def test_no_array_returns_empty(self):
        assert _extract_json_list("no JSON here") == []

    def test_invalid_json_returns_empty(self):
        assert _extract_json_list("[{invalid}]") == []

    def test_empty_array(self):
        assert _extract_json_list("[]") == []

    def test_array_embedded_in_text(self):
        text = 'Here is the result: [{"port": "GE1/0/0"}] done.'
        result = _extract_json_list(text)
        assert result == [{"port": "GE1/0/0"}]


# ---------------------------------------------------------------------------
# SchemaValidator.validate
# ---------------------------------------------------------------------------


class TestSchemaValidator:
    def test_lldp_valid(self):
        data = [
            {"local_port": "GE1/0/0", "remote_node": "R2", "remote_port": "GE0/0/1"}
        ]
        result = SchemaValidator.validate(data, "lldp_neighbors")
        assert len(result) == 1
        assert result[0]["local_port"] == "GE1/0/0"

    def test_lldp_port_normalized(self):
        data = [
            {
                "local_port": "GigabitEthernet1/0/0",
                "remote_node": "R2",
                "remote_port": "GigabitEthernet0/0/1",
            }
        ]
        result = SchemaValidator.validate(data, "lldp_neighbors")
        assert result[0]["local_port"] == "GE1/0/0"
        assert result[0]["remote_port"] == "GE0/0/1"

    def test_lldp_missing_required_key_returns_empty(self):
        data = [{"local_port": "GE1/0/0", "remote_node": "R2"}]  # missing remote_port
        result = SchemaValidator.validate(data, "lldp_neighbors")
        assert result == []

    def test_routing_table_valid(self):
        data = [
            {
                "prefix": "10.0.0.0/8",
                "next_hop": "10.1.1.2",
                "interface": "GE1/0/0",
                "protocol": "static",
            }
        ]
        result = SchemaValidator.validate(data, "routing_table")
        assert len(result) == 1

    def test_routing_table_interface_normalized(self):
        data = [
            {
                "prefix": "10.0.0.0/8",
                "next_hop": "10.1.1.2",
                "interface": "GigabitEthernet1/0/0",
                "protocol": "static",
            }
        ]
        result = SchemaValidator.validate(data, "routing_table")
        assert result[0]["interface"] == "GE1/0/0"

    def test_interface_brief_valid(self):
        data = [{"port": "GE1/0/0", "ip": "10.1.1.1", "status": "up"}]
        result = SchemaValidator.validate(data, "interface_brief")
        assert len(result) == 1

    def test_arp_table_valid(self):
        data = [{"ip": "10.1.1.2", "mac": "0012-3456-7890", "port": "GE1/0/0"}]
        result = SchemaValidator.validate(data, "arp_table")
        assert len(result) == 1

    def test_non_list_returns_empty(self):
        assert SchemaValidator.validate({"not": "a list"}, "lldp_neighbors") == []

    def test_non_dict_entry_returns_empty(self):
        assert SchemaValidator.validate(["not a dict"], "lldp_neighbors") == []

    def test_unknown_command_type_no_required_keys(self):
        # Unknown command type has no schema → passes with anything
        data = [{"anything": "goes"}]
        result = SchemaValidator.validate(data, "unknown_type")
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        assert SchemaValidator.validate([], "lldp_neighbors") == []


# ---------------------------------------------------------------------------
# TrackBClient (budget / caching helpers)
# ---------------------------------------------------------------------------


class TestTrackBClient:
    def test_budget_remaining_initial(self):
        client = TrackBClient("http://localhost:8000", daily_limit=1000)
        assert client.budget_remaining == 1000

    def test_budget_remaining_decreases(self):
        client = TrackBClient("http://localhost:8000", daily_limit=1000)
        client.budget_used = 300
        assert client.budget_remaining == 700

    def test_budget_remaining_floor_zero(self):
        client = TrackBClient("http://localhost:8000", daily_limit=100)
        client.budget_used = 200
        assert client.budget_remaining == 0

    @pytest.mark.parametrize(
        "command, expected_type",
        [
            ("display lldp neighbor brief", "lldp_neighbors"),
            ("display ip routing-table", "routing_table"),
            ("show ip route", "routing_table"),
            ("display arp", "arp_table"),
            ("display interface brief", "interface_brief"),
            ("show interface brief", "interface_brief"),
            ("unknown-command", "unknown"),
        ],
    )
    def test_map_command_type(self, command, expected_type):
        client = TrackBClient("http://localhost:8000")
        assert client._map_command_type(command) == expected_type

    def test_cache_key_deterministic(self):
        client = TrackBClient("http://localhost:8000")
        k1 = client._cache_key("s1", "R1", "display lldp neighbor brief")
        k2 = client._cache_key("s1", "R1", "display lldp neighbor brief")
        k3 = client._cache_key("s1", "R2", "display lldp neighbor brief")
        assert k1 == k2
        assert k1 != k3

    def test_execute_returns_empty_when_budget_exhausted(self):
        client = TrackBClient("http://localhost:8000", daily_limit=0)
        raw, vendor, cmd_type = client.execute(
            "s1", "R1", "display lldp neighbor brief"
        )
        assert raw == ""
        assert vendor == "unknown"

    def test_execute_caches_result(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": "test output",
            "vendor": "huawei",
            "command_type": "lldp_neighbors",
        }
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp) as mock_post:
            client = TrackBClient("http://localhost:8000", daily_limit=100)
            r1 = client.execute("s1", "R1", "display lldp neighbor brief")
            r2 = client.execute("s1", "R1", "display lldp neighbor brief")
        assert r1 == r2
        assert mock_post.call_count == 1  # cached on second call

    def test_execute_increments_budget(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": "out",
            "vendor": "huawei",
            "command_type": "lldp_neighbors",
        }
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp):
            client = TrackBClient("http://localhost:8000", daily_limit=100)
            client.execute("s1", "R1", "display lldp neighbor brief")
        assert client.budget_used == 1
