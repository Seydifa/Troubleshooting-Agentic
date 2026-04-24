"""
test_tools_track_a.py — Tests for src/tools/tools_track_a.py
(pure-Python feature extractor functions; TrackAClient HTTP calls are mocked).
"""

from __future__ import annotations

import pytest

from src.tools.tools_track_a import (
    build_feature_vector,
    classify_problem_type,
    compute_a3_threshold_db,
    detect_handover_failure,
    parse_throughput_series,
)


# ---------------------------------------------------------------------------
# parse_throughput_series
# ---------------------------------------------------------------------------


class TestParseThroughputSeries:
    def test_empty_data(self):
        result = parse_throughput_series({})
        assert result["min_mbps"] == 0.0
        assert result["max_mbps"] == 0.0
        assert result["avg_mbps"] == 0.0
        assert result["drop_pct"] == 0.0
        assert result["degradation_timestamp"] is None

    def test_empty_records_key(self):
        result = parse_throughput_series({"data": []})
        assert result["avg_mbps"] == 0.0

    def test_normal_records(self):
        records = [
            {"timestamp": "t1", "throughput_mbps": 100.0},
            {"timestamp": "t2", "throughput_mbps": 80.0},
            {"timestamp": "t3", "throughput_mbps": 20.0},  # < 50% of max=100
        ]
        result = parse_throughput_series({"data": records})
        assert result["min_mbps"] == pytest.approx(20.0)
        assert result["max_mbps"] == pytest.approx(100.0)
        assert result["avg_mbps"] == pytest.approx((100 + 80 + 20) / 3)
        # 1 out of 3 samples below 50 Mbps
        assert result["drop_pct"] == pytest.approx(1 / 3)

    def test_degradation_timestamp_recorded(self):
        records = [
            {"timestamp": "t1", "throughput_mbps": 100.0},
            {"timestamp": "t2", "throughput_mbps": 10.0},
        ]
        result = parse_throughput_series({"data": records})
        assert result["degradation_timestamp"] == "t2"

    def test_no_degradation_timestamp_when_all_above_threshold(self):
        records = [
            {"timestamp": "t1", "throughput_mbps": 80.0},
            {"timestamp": "t2", "throughput_mbps": 90.0},
        ]
        result = parse_throughput_series({"data": records})
        assert result["drop_pct"] == 0.0
        assert result["degradation_timestamp"] is None

    def test_records_key_alternative(self):
        records = [{"throughput_mbps": 50.0}]
        result = parse_throughput_series({"records": records})
        assert result["avg_mbps"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# compute_a3_threshold_db
# ---------------------------------------------------------------------------


class TestComputeA3Threshold:
    def test_formula(self):
        # (offset + hyst) * 0.5
        assert compute_a3_threshold_db(10, 2) == pytest.approx(6.0)
        assert compute_a3_threshold_db(0, 0) == pytest.approx(0.0)
        assert compute_a3_threshold_db(6, 4) == pytest.approx(5.0)

    def test_typical_values(self):
        # Common real-world config: offset=10, hyst=2 → 6 dB threshold
        result = compute_a3_threshold_db(10, 2)
        assert result == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# detect_handover_failure
# ---------------------------------------------------------------------------


class TestDetectHandoverFailure:
    def test_handover_should_trigger(self):
        # neighbor is 10 dB stronger than serving, threshold is 6 dB → HO failure
        result = detect_handover_failure(
            serving_rsrp=-90.0,
            neighbor_rsrp=-80.0,
            offset_05db=10,
            hyst_05db=2,
        )
        assert result["handover_failure"] is True
        assert result["delta_db"] == pytest.approx(10.0)
        assert result["threshold_db"] == pytest.approx(6.0)
        assert result["gap_db"] == pytest.approx(4.0)  # 10 - 6

    def test_no_handover_failure(self):
        # neighbor is only 3 dB stronger, threshold is 6 dB → no HO failure
        result = detect_handover_failure(
            serving_rsrp=-90.0,
            neighbor_rsrp=-87.0,
            offset_05db=10,
            hyst_05db=2,
        )
        assert result["handover_failure"] is False
        assert result["gap_db"] < 0

    def test_exactly_at_threshold(self):
        # delta_db == threshold_db → gap_db = 0 → HO failure (boundary)
        result = detect_handover_failure(
            serving_rsrp=-90.0,
            neighbor_rsrp=-84.0,  # delta = 6.0
            offset_05db=10,
            hyst_05db=2,  # threshold = 6.0
        )
        assert result["gap_db"] == pytest.approx(0.0)
        assert result["handover_failure"] is True

    def test_output_keys_present(self):
        result = detect_handover_failure(-90, -85, 10, 2)
        assert set(result.keys()) == {
            "delta_db",
            "threshold_db",
            "handover_failure",
            "gap_db",
        }


# ---------------------------------------------------------------------------
# classify_problem_type
# ---------------------------------------------------------------------------


class TestClassifyProblemType:
    def _base_features(self, **overrides):
        base = {
            "serving_rsrp": -85.0,
            "serving_sinr": 15.0,
            "handover_failure": False,
            "gap_db": -2.0,
            "neighbor_missing": False,
            "pdcch_symbol_count": 2,
        }
        base.update(overrides)
        return base

    def test_late_handover(self):
        f = self._base_features(handover_failure=True, gap_db=4.0)
        assert classify_problem_type(f) == "LATE_HANDOVER"

    def test_neighbor_missing(self):
        f = self._base_features(neighbor_missing=True)
        assert classify_problem_type(f) == "NEIGHBOR_MISSING"

    def test_interference(self):
        f = self._base_features(serving_sinr=-3.0, serving_rsrp=-95.0)
        assert classify_problem_type(f) == "INTERFERENCE"

    def test_coverage_hole(self):
        f = self._base_features(serving_rsrp=-115.0)
        assert classify_problem_type(f) == "COVERAGE_HOLE"

    def test_pdcch_issue(self):
        f = self._base_features(pdcch_symbol_count=5)
        assert classify_problem_type(f) == "PDCCH_ISSUE"

    def test_tx_power_issue(self):
        f = self._base_features(serving_rsrp=-105.0, serving_sinr=5.0)
        assert classify_problem_type(f) == "TX_POWER_ISSUE"

    def test_unknown(self):
        f = self._base_features()
        assert classify_problem_type(f) == "UNKNOWN"

    def test_late_handover_has_priority_over_neighbor_missing(self):
        # Both conditions true — LATE_HANDOVER wins (first in priority order)
        f = self._base_features(
            handover_failure=True, gap_db=2.0, neighbor_missing=True
        )
        assert classify_problem_type(f) == "LATE_HANDOVER"


# ---------------------------------------------------------------------------
# build_feature_vector
# ---------------------------------------------------------------------------


class TestBuildFeatureVector:
    def _make_features(self, **overrides):
        base = {
            "drop_pct": 0.2,
            "serving_sinr": 10.0,
            "delta_db": 5.0,
            "threshold_db": 6.0,
            "pci_stable": True,
            "handover_failure": False,
            "neighbor_missing": False,
            "neighbor_count": 4,
        }
        base.update(overrides)
        return base

    def test_output_length(self):
        fv = build_feature_vector(self._make_features())
        assert len(fv) == 8

    def test_all_floats(self):
        fv = build_feature_vector(self._make_features())
        assert all(isinstance(v, float) for v in fv)

    def test_values_clamped(self):
        # Extreme values should be clamped
        fv = build_feature_vector(
            self._make_features(
                drop_pct=5.0,  # clamp to 1.0
                serving_sinr=999,  # clamp to 1.0
            )
        )
        assert fv[0] == pytest.approx(1.0)
        assert fv[1] == pytest.approx(1.0)

    def test_binary_flags(self):
        fv_ho = build_feature_vector(self._make_features(handover_failure=True))
        fv_no = build_feature_vector(self._make_features(handover_failure=False))
        assert fv_ho[5] == pytest.approx(1.0)
        assert fv_no[5] == pytest.approx(0.0)

    def test_pci_stable_flag(self):
        fv = build_feature_vector(self._make_features(pci_stable=False))
        assert fv[4] == pytest.approx(0.0)

    def test_empty_features_gives_defaults(self):
        fv = build_feature_vector({})
        assert len(fv) == 8
        assert all(isinstance(v, float) for v in fv)


# ---------------------------------------------------------------------------
# TrackAClient (HTTP methods mocked)
# ---------------------------------------------------------------------------


class TestTrackAClient:
    def test_cache_key_deterministic(self):
        from src.tools.tools_track_a import TrackAClient

        client = TrackAClient("http://localhost:8000")
        k1 = client._cache_key("endpoint", "sid-1", {"a": 1})
        k2 = client._cache_key("endpoint", "sid-1", {"a": 1})
        k3 = client._cache_key("endpoint", "sid-2", {"a": 1})
        assert k1 == k2
        assert k1 != k3

    def test_get_caches_result(self):
        from unittest.mock import MagicMock, patch
        from src.tools.tools_track_a import TrackAClient

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status.return_value = None
        with patch("requests.get", return_value=mock_resp) as mock_get:
            client = TrackAClient("http://localhost:8000")
            r1 = client.throughput_logs("s1")
            r2 = client.throughput_logs("s1")
        assert r1 == r2
        # Only one HTTP call due to caching
        assert mock_get.call_count == 1

    def test_get_returns_empty_dict_on_error(self):
        from unittest.mock import patch
        from src.tools.tools_track_a import TrackAClient

        with patch("requests.get", side_effect=Exception("HTTP 500")):
            client = TrackAClient("http://localhost:8000")
            result = client.user_plane_data("s1")
        assert result == {}
