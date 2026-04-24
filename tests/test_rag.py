"""
test_rag.py — Tests for src/rag.py (TabularRAG + RAGEntry).
All tests operate on in-memory state — no file I/O or LLM calls.
"""

from __future__ import annotations

import pickle
import tempfile
from pathlib import Path

import numpy as np
import pytest
from sklearn.neighbors import NearestNeighbors

from src.rag import RAGEntry, TabularRAG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entries():
    return [
        RAGEntry(
            "s1",
            "LATE_HANDOVER",
            [1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5],
            "RSRP: -90",
            "C1",
            "Late HO",
        ),
        RAGEntry(
            "s2",
            "INTERFERENCE",
            [0.1, -0.5, -0.1, 0.2, 1.0, 0.0, 0.0, 0.3],
            "SINR: -5",
            "C2",
            "Interference",
        ),
        RAGEntry(
            "s3",
            "COVERAGE_HOLE",
            [0.8, -1.0, -0.8, 0.1, 1.0, 0.0, 0.0, 0.1],
            "RSRP: -115",
            "C3",
            "Coverage",
        ),
    ]


def _build_rag(k: int = 2) -> TabularRAG:
    rag = TabularRAG(k=k)
    entries = _make_entries()
    X = np.array([e.feature_vector for e in entries], dtype=float)
    knn = NearestNeighbors(n_neighbors=k, metric="euclidean")
    knn.fit(X)
    rag._entries = entries
    rag._X = X
    rag._knn = knn
    return rag


# ---------------------------------------------------------------------------
# RAGEntry
# ---------------------------------------------------------------------------


class TestRAGEntry:
    def test_to_context_block_contains_fields(self):
        entry = RAGEntry(
            scenario_id="s1",
            problem_type="LATE_HANDOVER",
            feature_vector=[0.1] * 8,
            tool_summary="RSRP: -90 dBm",
            answer="C5",
            reasoning_template="Handover should have fired.",
        )
        block = entry.to_context_block()
        assert "s1" in block
        assert "LATE_HANDOVER" in block
        assert "RSRP: -90 dBm" in block
        assert "C5" in block
        assert "Handover should have fired." in block

    def test_to_context_block_format(self):
        entry = RAGEntry("s2", "INTERFERENCE", [0.0] * 8, "", "C3", "")
        block = entry.to_context_block()
        assert block.startswith("--- Example")
        assert "ANSWER:" in block


# ---------------------------------------------------------------------------
# TabularRAG
# ---------------------------------------------------------------------------


class TestTabularRAG:
    def test_len_empty(self):
        rag = TabularRAG()
        assert len(rag) == 0

    def test_len_after_build(self):
        rag = _build_rag(k=2)
        assert len(rag) == 3

    def test_retrieve_returns_k_entries(self):
        rag = _build_rag(k=2)
        query = [1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5]  # identical to s1
        results = rag.retrieve(query)
        assert len(results) == 2

    def test_retrieve_most_similar_first(self):
        rag = _build_rag(k=2)
        # Query identical to s1
        query = [1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5]
        results = rag.retrieve(query)
        assert results[0].scenario_id == "s1"

    def test_retrieve_on_empty_index_returns_empty(self):
        rag = TabularRAG(k=3)
        results = rag.retrieve([0.0] * 8)
        assert results == []

    def test_format_context_returns_string(self):
        rag = _build_rag(k=2)
        ctx = rag.format_context([1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5])
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_format_context_empty_index_returns_empty(self):
        rag = TabularRAG(k=2)
        assert rag.format_context([0.0] * 8) == ""

    def test_format_context_contains_all_retrieved(self):
        rag = _build_rag(k=2)
        ctx = rag.format_context([1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5])
        # Should contain 2 entries
        assert ctx.count("--- Example") == 2

    def test_save_and_load(self):
        rag = _build_rag(k=2)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_rag.pkl")
            rag.save(path)
            assert Path(path).exists()

            loaded = TabularRAG()
            loaded.load(path)
            assert len(loaded) == 3
            assert loaded._k == 2

    def test_from_file_classmethod(self):
        rag = _build_rag(k=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "rag.pkl")
            rag.save(path)
            loaded = TabularRAG.from_file(path)
            assert len(loaded) == 3

    def test_loaded_rag_can_retrieve(self):
        rag = _build_rag(k=2)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "rag.pkl")
            rag.save(path)
            loaded = TabularRAG.from_file(path)
            results = loaded.retrieve([1.0, 0.0, 0.5, 0.3, 1.0, 1.0, 0.0, 0.5])
            assert len(results) == 2
            assert results[0].scenario_id == "s1"

    def test_k_capped_to_available_entries(self):
        # k=5 but only 3 entries — should not error
        rag = TabularRAG(k=5)
        entries = _make_entries()
        X = np.array([e.feature_vector for e in entries], dtype=float)
        n_neighbors = min(5, len(entries))
        knn = NearestNeighbors(n_neighbors=n_neighbors, metric="euclidean")
        knn.fit(X)
        rag._entries = entries
        rag._X = X
        rag._knn = knn
        results = rag.retrieve([0.0] * 8)
        assert len(results) == 3
