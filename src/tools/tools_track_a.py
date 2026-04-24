"""
tools_track_a.py — Track A HTTP Client & Feature Extractors

Two responsibilities, zero LLM:
1. TrackAClient  — cached HTTP wrapper for all Track A Tool Server endpoints.
2. Feature extractor functions — deterministic Python math that converts raw
   API responses into structured numeric features.

Dependencies: requests, pandas, state
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from src.state import ProblemTypeA

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TrackAClient
# ---------------------------------------------------------------------------


class TrackAClient:
    """Cached HTTP wrapper for all Track A Tool Server endpoints.

    Every response is cached by ``md5(endpoint + scenario_id + repr(params))``
    so that retrying the LangGraph analysis_node never re-hits the API.
    """

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, endpoint: str, scenario_id: str, params: dict) -> str:
        raw = f"{endpoint}:{scenario_id}:{repr(sorted(params.items()))}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get(self, endpoint: str, scenario_id: str, params: dict = {}) -> Any:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        key = self._cache_key(endpoint, scenario_id, params)
        if key in self._cache:
            return self._cache[key]
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"X-Scenario-Id": scenario_id},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("TrackAClient GET %s failed: %s", url, exc)
            data = {}
        self._cache[key] = data
        return data

    # ------------------------------------------------------------------
    # Endpoint wrappers
    # ------------------------------------------------------------------

    def throughput_logs(self, scenario_id: str) -> Dict[str, Any]:
        return self._get("throughput-logs", scenario_id)

    def user_plane_data(self, scenario_id: str) -> Dict[str, Any]:
        return self._get("user-plane-data/json", scenario_id)

    def config_data(self, scenario_id: str) -> Dict[str, Any]:
        return self._get("config-data/json", scenario_id)

    def user_location(self, scenario_id: str) -> Dict[str, Any]:
        return self._get("user-location", scenario_id)

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------

    def save_cache(self, path: str) -> None:
        """Persist the in-memory response cache to a pickle file."""
        with open(path, "wb") as fh:
            pickle.dump(self._cache, fh)
        logger.info(
            "TrackAClient: cache saved to %s (%d entries)", path, len(self._cache)
        )

    def load_cache(self, path: str) -> None:
        """Load a previously saved cache from disk (merges into current cache)."""
        with open(path, "rb") as fh:
            loaded: Dict[str, Any] = pickle.load(fh)
        self._cache.update(loaded)
        logger.info("TrackAClient: loaded %d cache entries from %s", len(loaded), path)

    def warm_all(self, scenario_ids: List[str]) -> None:
        """Pre-fetch all tool endpoints for every scenario_id in the list.

        Call this before inference so every subsequent _get() is a cache hit.
        """
        endpoints = [
            ("throughput-logs", self.throughput_logs),
            ("user-plane-data/json", self.user_plane_data),
            ("config-data/json", self.config_data),
            ("user-location", self.user_location),
        ]
        total = len(scenario_ids) * len(endpoints)
        done = 0
        for sid in scenario_ids:
            for ep_name, fn in endpoints:
                fn(sid)
                done += 1
                if done % 10 == 0 or done == total:
                    logger.info("warm_all: %d/%d fetched", done, total)
        logger.info("warm_all: complete — %d entries cached", len(self._cache))


# ---------------------------------------------------------------------------
# Feature Extractor Functions (pure Python — no LLM, no side effects)
# ---------------------------------------------------------------------------


def parse_throughput_series(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse raw throughput API response into summary statistics.

    Parameters
    ----------
    data : dict
        Raw JSON from throughput_logs endpoint.  Expected to contain either
        a ``"data"`` key with a list of ``{timestamp, throughput_mbps}``
        records, or a ``"records"`` key.

    Returns
    -------
    dict with keys:
        min_mbps, max_mbps, avg_mbps, drop_pct, degradation_timestamp
    """
    records = data.get("data") or data.get("records") or []

    # Handle {"Logs": "csv_string"} format from /throughput-logs endpoint
    if not records and "Logs" in data:
        try:
            import io

            df_raw = pd.read_csv(io.StringIO(data["Logs"]), sep="|")
            records = df_raw.to_dict("records")
        except Exception as exc:
            logger.warning("parse_throughput_series: CSV parse failed: %s", exc)

    if not records:
        return {
            "min_mbps": 0.0,
            "max_mbps": 0.0,
            "avg_mbps": 0.0,
            "drop_pct": 0.0,
            "degradation_timestamp": None,
        }

    try:
        df = pd.DataFrame(records)
        # Flexible column name handling
        tput_col = next(
            c for c in df.columns if "throughput" in c.lower() or "mbps" in c.lower()
        )
        time_col = next(
            (c for c in df.columns if "time" in c.lower() or "ts" in c.lower()), None
        )
        series = df[tput_col].astype(float)
        min_v = float(series.min())
        max_v = float(series.max())
        avg_v = float(series.mean())

        # drop_pct: fraction of samples below 50 % of the max value
        half_max = max_v * 0.5 if max_v > 0 else 0.0
        drop_count = int((series < half_max).sum())
        drop_pct = drop_count / len(series) if len(series) > 0 else 0.0

        # First timestamp where throughput drops below 50 % of max
        degradation_ts = None
        if time_col is not None and drop_count > 0:
            degrade_mask = series < half_max
            first_idx = degrade_mask.idxmax() if degrade_mask.any() else None
            if first_idx is not None:
                degradation_ts = str(df.loc[first_idx, time_col])

        return {
            "min_mbps": min_v,
            "max_mbps": max_v,
            "avg_mbps": avg_v,
            "drop_pct": drop_pct,
            "degradation_timestamp": degradation_ts,
        }
    except Exception as exc:
        logger.warning("parse_throughput_series failed: %s", exc)
        return {
            "min_mbps": 0.0,
            "max_mbps": 0.0,
            "avg_mbps": 0.0,
            "drop_pct": 0.0,
            "degradation_timestamp": None,
        }


def extract_features_from_rows(
    up_rows: List[Dict[str, Any]],
    config_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract 5G RF features from user-plane and config-data rows.

    Parameters
    ----------
    up_rows : list[dict]
        Rows from ``/user-plane-data/json`` (each row is one measurement sample).
    config_rows : list[dict]
        Rows from ``/config-data/json`` (each row is one cell's configuration).

    Returns
    -------
    dict
        Feature dict compatible with ``classify_problem_type`` and
        ``build_feature_vector``.
    """
    # ---- column names as used in the real data ----
    TPUT_COL = "5G KPI PCell Layer2 MAC DL Throughput [Mbps]"
    RSRP_COL = "5G KPI PCell RF Serving SS-RSRP [dBm]"
    SINR_COL = "5G KPI PCell RF Serving SS-SINR [dB]"
    PCI_COL = "5G KPI PCell RF Serving PCI"
    NB_PCI_PREFIX = "Measurement PCell Neighbor Cell Top Set(Cell Level) Top "
    NB_RSRP_SUFFIX = " Filtered Tx BRSRP [dBm]"
    NB_PCI_SUFFIX = " PCI"
    A3_OFFSET_COL = "IntraFreqHoA3Offset [0.5dB]"
    A3_HYST_COL = "IntraFreqHoA3Hyst [0.5dB]"
    PDCCH_COL = "PdcchOccupiedSymbolNum"
    NB_CFG_COL = "PCell Neighbor Cell (gNodeBID_ARFCN_PCI)"

    # ---- defaults ----
    defaults: Dict[str, Any] = {
        "min_mbps": 0.0,
        "max_mbps": 0.0,
        "avg_mbps": 0.0,
        "drop_pct": 0.0,
        "degradation_timestamp": None,
        "serving_rsrp": -110.0,
        "serving_sinr": 0.0,
        "delta_db": 0.0,
        "threshold_db": 6.0,
        "handover_failure": False,
        "gap_db": -6.0,
        "neighbor_missing": False,
        "neighbor_count": 0,
        "pci_stable": True,
        "pdcch_symbol_count": 2,
    }

    if not up_rows:
        return defaults

    df = pd.DataFrame(up_rows)

    # ---- throughput stats ----
    tput_stats: Dict[str, Any] = {
        "min_mbps": 0.0,
        "max_mbps": 0.0,
        "avg_mbps": 0.0,
        "drop_pct": 0.0,
        "degradation_timestamp": None,
    }
    if TPUT_COL in df.columns:
        series = pd.to_numeric(df[TPUT_COL], errors="coerce").dropna()
        if len(series) > 0:
            max_v = float(series.max())
            half_max = max_v * 0.5 if max_v > 0 else 0.0
            drop_mask = series < half_max
            tput_stats = {
                "min_mbps": float(series.min()),
                "max_mbps": max_v,
                "avg_mbps": float(series.mean()),
                "drop_pct": float(drop_mask.sum() / len(series)),
                "degradation_timestamp": None,
            }
            if drop_mask.any():
                try:
                    time_col = next(
                        c
                        for c in df.columns
                        if "time" in c.lower() or "timestamp" in c.lower()
                    )
                    tput_stats["degradation_timestamp"] = str(
                        df.loc[drop_mask.idxmax(), time_col]
                    )
                except (StopIteration, KeyError):
                    pass

    # ---- serving cell RF metrics ----
    serving_rsrp: float = -110.0
    if RSRP_COL in df.columns:
        v = pd.to_numeric(df[RSRP_COL], errors="coerce").dropna()
        if len(v) > 0:
            serving_rsrp = float(v.median())

    serving_sinr: float = 0.0
    if SINR_COL in df.columns:
        v = pd.to_numeric(df[SINR_COL], errors="coerce").dropna()
        if len(v) > 0:
            serving_sinr = float(v.median())

    serving_pci: Optional[int] = None
    if PCI_COL in df.columns:
        v = pd.to_numeric(df[PCI_COL], errors="coerce").dropna()
        if len(v) > 0:
            serving_pci = int(v.mode().iloc[0])

    # ---- neighbor PCIs and best RSRP from measurement data ----
    measured_nb_pcis: set = set()
    best_nb_rsrp = serving_rsrp - 5.0
    for n in range(1, 6):
        pci_col = f"{NB_PCI_PREFIX}{n}{NB_PCI_SUFFIX}"
        rsrp_col = f"{NB_PCI_PREFIX}{n}{NB_RSRP_SUFFIX}"
        if pci_col in df.columns:
            vals = pd.to_numeric(df[pci_col], errors="coerce").dropna().astype(int)
            measured_nb_pcis.update(vals.tolist())
        if rsrp_col in df.columns and n == 1:
            v = pd.to_numeric(df[rsrp_col], errors="coerce").dropna()
            if len(v) > 0:
                best_nb_rsrp = float(v.max())

    # ---- cell config: A3 params, PDCCH, configured neighbors ----
    offset_05db: float = 10.0
    hyst_05db: float = 2.0
    pdcch_sym: int = 2
    configured_nb_pcis: set = set()

    if config_rows and serving_pci is not None:
        cfg_df = pd.DataFrame(config_rows)
        if "PCI" in cfg_df.columns:
            match = cfg_df[pd.to_numeric(cfg_df["PCI"], errors="coerce") == serving_pci]
            if not match.empty:
                row = match.iloc[0]
                try:
                    offset_05db = float(row.get(A3_OFFSET_COL, 10))
                except (TypeError, ValueError):
                    pass
                try:
                    hyst_05db = float(row.get(A3_HYST_COL, 2))
                except (TypeError, ValueError):
                    pass
                pdcch_str = str(row.get(PDCCH_COL, "2SYM"))
                if "SYM" in pdcch_str.upper():
                    try:
                        pdcch_sym = int(pdcch_str.upper().replace("SYM", "").strip())
                    except ValueError:
                        pdcch_sym = 2
                nb_cell_str = str(row.get(NB_CFG_COL, ""))
                for entry in nb_cell_str.strip("[]").split(","):
                    entry = entry.strip()
                    if "_" in entry:
                        try:
                            configured_nb_pcis.add(int(entry.split("_")[-1]))
                        except ValueError:
                            pass

    # ---- neighbor_missing: strong measured PCI not in configured list ----
    neighbor_missing = (
        bool(measured_nb_pcis)
        and bool(configured_nb_pcis)
        and bool(measured_nb_pcis - configured_nb_pcis)
    )

    # ---- handover analysis ----
    ho_info = detect_handover_failure(
        serving_rsrp, best_nb_rsrp, offset_05db, hyst_05db
    )

    return {
        **tput_stats,
        "serving_rsrp": serving_rsrp,
        "serving_sinr": serving_sinr,
        "neighbor_count": len(measured_nb_pcis),
        "neighbor_missing": neighbor_missing,
        "pci_stable": True,
        "pdcch_symbol_count": pdcch_sym,
        **ho_info,
    }


def compute_a3_threshold_db(offset_05db: float, hyst_05db: float) -> float:
    """Convert A3 offset and hysteresis from 0.5 dB units to dB.

    A3 event threshold (dB) = (IntraFreqHoA3Offset + A3HystDB) × 0.5

    Parameters
    ----------
    offset_05db : float
        IntraFreqHoA3Offset value in 0.5 dB units (as stored in cell config).
    hyst_05db : float
        A3 Hysteresis value in 0.5 dB units.

    Returns
    -------
    float
        Total A3 threshold in dB.
    """
    return (offset_05db + hyst_05db) * 0.5


def detect_handover_failure(
    serving_rsrp: float,
    neighbor_rsrp: float,
    offset_05db: float,
    hyst_05db: float,
) -> Dict[str, Any]:
    """Determine whether an A3 handover failure has occurred.

    A3 event SHOULD fire when:
        neighbor_rsrp > serving_rsrp + threshold_db

    If the gap is large enough to trigger A3 but handover has not occurred,
    we call it a LATE_HANDOVER.

    Parameters
    ----------
    serving_rsrp : float
        Serving cell RSRP in dBm.
    neighbor_rsrp : float
        Best neighbouring cell RSRP in dBm.
    offset_05db : float
        IntraFreqHoA3Offset in 0.5 dB units.
    hyst_05db : float
        A3HystDB in 0.5 dB units.

    Returns
    -------
    dict with keys:
        delta_db, threshold_db, handover_failure (bool), gap_db
    """
    threshold_db = compute_a3_threshold_db(offset_05db, hyst_05db)
    delta_db = neighbor_rsrp - serving_rsrp
    # gap_db: how far above (positive) or below (negative) the threshold the delta is
    gap_db = delta_db - threshold_db
    handover_failure = gap_db >= 0  # A3 should have triggered but didn't
    return {
        "delta_db": round(delta_db, 2),
        "threshold_db": round(threshold_db, 2),
        "handover_failure": handover_failure,
        "gap_db": round(gap_db, 2),
    }


def classify_problem_type(features: Dict[str, Any]) -> str:
    """Classify the RF problem category from the pre-computed feature dict.

    Decision rules are applied in priority order.

    Parameters
    ----------
    features : dict
        Must contain: serving_rsrp, serving_sinr, handover_failure,
        neighbor_missing, pdcch_symbol_count.

    Returns
    -------
    str
        One of the ProblemTypeA string values.
    """
    serving_rsrp: float = features.get("serving_rsrp", -110.0)
    serving_sinr: float = features.get("serving_sinr", 0.0)
    handover_failure: bool = features.get("handover_failure", False)
    neighbor_missing: bool = features.get("neighbor_missing", False)
    pdcch_symbol_count: int = features.get("pdcch_symbol_count", 2)

    # Priority order matters — first matching rule wins
    if handover_failure and features.get("gap_db", 0.0) >= 0:
        return ProblemTypeA.LATE_HANDOVER.value
    if neighbor_missing:
        return ProblemTypeA.NEIGHBOR_MISSING.value
    if serving_sinr < 0 and serving_rsrp > -100:
        return ProblemTypeA.INTERFERENCE.value
    if serving_rsrp < -110:
        return ProblemTypeA.COVERAGE_HOLE.value
    if pdcch_symbol_count not in (1, 2, 3):
        return ProblemTypeA.PDCCH_ISSUE.value
    # TX_POWER_ISSUE: low RSRP despite being close (sinr is reasonable but rsrp is low)
    if serving_rsrp < -100 and serving_sinr >= 0:
        return ProblemTypeA.TX_POWER_ISSUE.value
    return ProblemTypeA.UNKNOWN.value


def build_feature_vector(features: Dict[str, Any]) -> List[float]:
    """Build the normalized 8-dimensional feature vector for KNN RAG queries.

    Vector dimensions (all normalized to ~[0, 1]):
    [drop_pct, sinr/30, rsrp_delta/20, a3_threshold/10,
     pci_stable, ho_failure, neighbor_missing, neighbor_count/10]

    Parameters
    ----------
    features : dict
        Pre-computed feature dict from feature_extraction_node.

    Returns
    -------
    list[float]
        8-element normalized float vector.
    """

    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    drop_pct = _clamp(float(features.get("drop_pct", 0.0)), 0.0, 1.0)
    sinr_norm = _clamp(float(features.get("serving_sinr", 0.0)) / 30.0, -1.0, 1.0)
    rsrp_delta_norm = _clamp(float(features.get("delta_db", 0.0)) / 20.0, -1.0, 1.0)
    a3_thresh_norm = _clamp(float(features.get("threshold_db", 0.0)) / 10.0, 0.0, 1.0)
    pci_stable = 1.0 if features.get("pci_stable", True) else 0.0
    ho_failure = 1.0 if features.get("handover_failure", False) else 0.0
    neighbor_miss = 1.0 if features.get("neighbor_missing", False) else 0.0
    neighbor_count = _clamp(float(features.get("neighbor_count", 0)) / 10.0, 0.0, 1.0)

    return [
        drop_pct,
        sinr_norm,
        rsrp_delta_norm,
        a3_thresh_norm,
        pci_stable,
        ho_failure,
        neighbor_miss,
        neighbor_count,
    ]
