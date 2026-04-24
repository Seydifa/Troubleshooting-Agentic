"""
rag.py — Tabular RAG (Feature-Vector KNN Index) for Track A

Builds and queries a similarity index over Track A training examples.
Uses sklearn KNN on 8-dimensional feature vectors (not text embeddings).

Dependencies: sklearn, numpy, pickle, state, tools.tools_track_a
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.neighbors import NearestNeighbors

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RAGEntry
# ---------------------------------------------------------------------------


@dataclass
class RAGEntry:
    """A single training example stored in the RAG index.

    Attributes
    ----------
    scenario_id : str
    problem_type : str
        ProblemTypeA string value.
    feature_vector : list[float]
        8-dimensional normalized feature vector.
    tool_summary : str
        Short textual summary of the raw tool data (e.g. "RSRP: -95 dBm, SINR: -2 dB").
    answer : str
        Ground-truth answer (e.g. "C5|C9").
    reasoning_template : str
        Short chain-of-thought explanation used as few-shot context.
    """

    scenario_id: str
    problem_type: str
    feature_vector: List[float]
    tool_summary: str = ""
    answer: str = ""
    reasoning_template: str = ""

    def to_context_block(self) -> str:
        """Format this entry as a few-shot example string for prompt injection."""
        return (
            f"--- Example (scenario_id={self.scenario_id}) ---\n"
            f"Problem type: {self.problem_type}\n"
            f"Observed data: {self.tool_summary}\n"
            f"Reasoning: {self.reasoning_template}\n"
            f"ANSWER: {self.answer}\n"
        )


# ---------------------------------------------------------------------------
# TabularRAG
# ---------------------------------------------------------------------------


class TabularRAG:
    """Feature-vector KNN index over Track A training examples.

    Workflow
    --------
    1. Call ``build_from_train(train_json_path, client)`` once to fit the index.
    2. Optionally ``save(path)`` then ``load(path)`` on subsequent runs.
    3. Call ``retrieve(feature_vector)`` or ``format_context(feature_vector)``
       at query time.
    """

    def __init__(self, k: int = 3):
        self._k = k
        self._entries: List[RAGEntry] = []
        self._knn: Optional[NearestNeighbors] = None
        self._X: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_from_train(
        self,
        train_json_path: str,
        client: Any,  # TrackAClient
        *,
        max_examples: int = 2000,
    ) -> None:
        """Build the KNN index from a train.json file.

        For each training example the method:
        1. Fetches all tool-server data via ``client``.
        2. Extracts the feature vector.
        3. Stores a ``RAGEntry``.

        Parameters
        ----------
        train_json_path : str
            Path to the labelled training data JSON file.
        client : TrackAClient
            Initialized HTTP client for the Track A tool server.
        max_examples : int
            Maximum number of examples to index.
        """
        import json as _json
        from src.tools.tools_track_a import (
            extract_features_from_rows,
            classify_problem_type,
            build_feature_vector,
        )

        with open(train_json_path, "r", encoding="utf-8") as fh:
            train_data = _json.load(fh)

        if isinstance(train_data, dict):
            scenarios = train_data.get("data") or train_data.get("scenarios") or []
        else:
            scenarios = train_data

        scenarios = scenarios[:max_examples]
        entries: List[RAGEntry] = []
        vectors: List[List[float]] = []

        for scenario in scenarios:
            sid = scenario.get("scenario_id", "")
            answer = scenario.get("answer", "")

            try:
                # Fetch raw data from the two real endpoints
                up_data = client.user_plane_data(sid)
                cfg_data = client.config_data(sid)
                up_rows = up_data.get("rows", [])
                config_rows = cfg_data.get("rows", [])

                features: Dict[str, Any] = extract_features_from_rows(
                    up_rows, config_rows
                )

                problem_type = classify_problem_type(features)
                fv = build_feature_vector(features)

                tool_summary = (
                    f"RSRP: {features['serving_rsrp']:.1f} dBm, "
                    f"SINR: {features['serving_sinr']:.1f} dB, "
                    f"drop_pct: {features['drop_pct']:.2f}, "
                    f"HO_failure: {features['handover_failure']}"
                )

                entry = RAGEntry(
                    scenario_id=sid,
                    problem_type=problem_type,
                    feature_vector=fv,
                    tool_summary=tool_summary,
                    answer=answer,
                    reasoning_template=(
                        f"Problem classified as {problem_type} based on: "
                        f"RSRP={features['serving_rsrp']:.1f}, "
                        f"SINR={features['serving_sinr']:.1f}, "
                        f"HO_failure={features['handover_failure']}."
                    ),
                )
                entries.append(entry)
                vectors.append(fv)

            except Exception as exc:
                logger.warning("RAG build skipped scenario %s: %s", sid, exc)
                continue

        if not entries:
            logger.warning(
                "TabularRAG: no valid entries built from %s", train_json_path
            )
            return

        self._entries = entries
        self._X = np.array(vectors, dtype=float)
        n_neighbors = min(self._k, len(entries))
        self._knn = NearestNeighbors(
            n_neighbors=n_neighbors, metric="euclidean", algorithm="auto"
        )
        self._knn.fit(self._X)
        logger.info("TabularRAG: built index with %d entries", len(entries))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def retrieve(self, feature_vector: List[float]) -> List[RAGEntry]:
        """Return the top-k most similar RAGEntry objects.

        Parameters
        ----------
        feature_vector : list[float]
            8-dimensional query vector (output of build_feature_vector()).

        Returns
        -------
        list[RAGEntry]
            Up to ``self._k`` entries, ordered by similarity (most similar first).
        """
        if self._knn is None or self._X is None:
            logger.warning("TabularRAG.retrieve called on empty index")
            return []

        q = np.array(feature_vector, dtype=float).reshape(1, -1)
        distances, indices = self._knn.kneighbors(q)
        return [self._entries[i] for i in indices[0]]

    def format_context(self, feature_vector: List[float]) -> str:
        """Retrieve top-k entries and format them as a single few-shot context string.

        Parameters
        ----------
        feature_vector : list[float]

        Returns
        -------
        str
            Ready-to-inject few-shot context block.
        """
        entries = self.retrieve(feature_vector)
        if not entries:
            return ""
        return "\n\n".join(e.to_context_block() for e in entries)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the index to disk (pickle).

        Parameters
        ----------
        path : str
            File path, e.g. ``"rag_index.pkl"``.
        """
        state = {
            "k": self._k,
            "entries": self._entries,
            "knn": self._knn,
            "X": self._X,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(state, fh)
        logger.info(
            "TabularRAG: index saved to %s (%d entries)", path, len(self._entries)
        )

    def load(self, path: str) -> None:
        """Restore a previously saved index from disk.

        Parameters
        ----------
        path : str
            File path to the pickle file.
        """
        with open(path, "rb") as fh:
            state = pickle.load(fh)
        self._k = state["k"]
        self._entries = state["entries"]
        self._knn = state["knn"]
        self._X = state["X"]
        logger.info(
            "TabularRAG: loaded index from %s (%d entries)", path, len(self._entries)
        )

    @classmethod
    def from_file(cls, path: str) -> "TabularRAG":
        """Convenience constructor that loads an existing index file.

        Parameters
        ----------
        path : str

        Returns
        -------
        TabularRAG
        """
        instance = cls()
        instance.load(path)
        return instance

    def __len__(self) -> int:
        return len(self._entries)
