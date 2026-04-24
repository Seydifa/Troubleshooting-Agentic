"""
wandb_logger.py — Optional Weights & Biases integration for the telco benchmark.

Logs per-scenario agent outputs to a W&B Table so you can monitor progress
in real time during long runs (400+ scenarios) and catch issues early.

Usage
-----
from src.wandb_logger import WandbLogger

wl = WandbLogger(project="telco-troubleshooting", run_name="track-a-full-run")
wl.log_track_a(sid, answer, final_state, elapsed_s)
wl.log_eval(sid, answer, ground_truth, exact_match, final_state, elapsed_s)
wl.log_track_b(sid, answer, elapsed_s)
wl.log_summary({"accuracy": 0.87, "macro_f1": 0.85})
wl.finish()

Environment
-----------
Set WANDB_API_KEY (or call ``wandb.login()`` before creating WandbLogger).
If wandb is not installed or WANDB_API_KEY is unset, all calls silently no-op.
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TABLE_COLUMNS = [
    "idx",
    "scenario_id",
    "task_id",
    "track",
    "label",
    "prediction",
    "exact_match",
    "status",
    "elapsed_s",
    "raw_output",
    "reasoning",
    "rag_context",
]

# Rebuild and log the table to W&B every N rows (for real-time table monitoring)
_DEFAULT_FLUSH_EVERY = 10


class WandbLogger:
    """Thread-safe W&B logger that streams per-scenario results during a run.

    Parameters
    ----------
    project : str
        W&B project name (created automatically if it does not exist).
    run_name : str, optional
        Human-readable display name for this run.
    config : dict, optional
        Hyperparameters / metadata to store with the run (model, split, etc.).
    flush_every : int
        Rebuild and log the results table every *flush_every* rows so you can
        inspect it in the W&B UI while the run is still going.  Default: 10.
    enabled : bool
        Hard-disable all logging (useful in unit tests).
    """

    def __init__(
        self,
        project: str = "telco-troubleshooting",
        run_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        flush_every: int = _DEFAULT_FLUSH_EVERY,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._wandb = None
        self._run = None
        self._flush_every = flush_every
        self._rows: list[list] = []
        self._lock = threading.Lock()
        self._step = 0

        if not enabled:
            return

        try:
            import wandb as _wandb

            self._wandb = _wandb
        except ImportError:
            logger.warning(
                "wandb not installed — W&B logging disabled. Run: pip install wandb"
            )
            self._enabled = False
            return

        import os

        _api_key = os.getenv("WANDB_API_KEY", "")
        if not _api_key:
            # wandb may still be logged in via netrc / saved credentials
            try:
                if not self._wandb.api.api_key:
                    raise ValueError("no key")
            except Exception:
                logger.warning(
                    "WANDB_API_KEY not set and no saved credentials found — "
                    "W&B logging disabled.  Set the env var or call wandb.login()."
                )
                self._enabled = False
                return

        try:
            self._run = self._wandb.init(
                project=project,
                name=run_name,
                config=config or {},
                reinit=True,
            )
            # Ensure the run is always closed cleanly, even if finish() is
            # never called explicitly (e.g. notebook cell exception / interrupt).
            atexit.register(self._atexit_finish)
            logger.info("W&B run started: %s", self._run.url)
        except Exception as exc:
            logger.warning("W&B init failed (%s) — logging disabled.", exc)
            self._enabled = False

    def _atexit_finish(self) -> None:
        """Called automatically at interpreter exit to prevent 'crashed' status."""
        if self._enabled and self._run is not None:
            try:
                with self._lock:
                    self._flush_table()
                self._run.finish()
            except Exception:
                pass

    def __del__(self) -> None:
        """Last-resort cleanup in case atexit doesn't fire (e.g. Jupyter kernel restart)."""
        try:
            self._atexit_finish()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def log_track_a(
        self,
        scenario_id: str,
        answer: str,
        final_state: Dict[str, Any],
        elapsed_s: float,
        status: str = "ok",
    ) -> None:
        """Log one Track A test-inference result (no ground truth available)."""
        if not self._enabled:
            return
        self._log_row(
            scenario_id=scenario_id,
            task_id=str(final_state.get("task_id", "")),
            track="A",
            label="",
            prediction=answer,
            exact_match=None,
            status=status,
            elapsed_s=elapsed_s,
            raw_output=str(final_state.get("raw_answer", ""))[:1000],
            reasoning=str(final_state.get("reasoning", ""))[:1000],
            rag_context=str(final_state.get("context", "") or final_state.get("rag_context", ""))[:1500],
        )

    def log_eval(
        self,
        scenario_id: str,
        answer: str,
        ground_truth: str,
        exact_match: bool,
        final_state: Dict[str, Any],
        elapsed_s: float,
        status: str = "ok",
    ) -> None:
        """Log one labelled eval scenario (track_a_evaluation notebook §10).

        Includes ``label`` and ``exact_match`` columns so you can
        watch accuracy climb in real time on the W&B dashboard.
        """
        if not self._enabled:
            return
        self._log_row(
            scenario_id=scenario_id,
            task_id=str(final_state.get("task_id", "")),
            track="A",
            label=ground_truth,
            prediction=answer,
            exact_match=exact_match,
            status=status,
            elapsed_s=elapsed_s,
            raw_output=str(final_state.get("raw_answer", ""))[:1000],
            reasoning=str(final_state.get("reasoning", ""))[:1000],
            rag_context=str(final_state.get("context", "") or final_state.get("rag_context", ""))[:1500],
        )

    def log_track_b(
        self,
        scenario_id: str,
        answer: str,
        final_state: Dict[str, Any],
        elapsed_s: float,
        status: str = "ok",
    ) -> None:
        """Log one Track B result."""
        if not self._enabled:
            return
        self._log_row(
            scenario_id=scenario_id,
            task_id=str(final_state.get("task_id", "")),
            track="B",
            label="",
            prediction=answer,
            exact_match=None,
            status=status,
            elapsed_s=elapsed_s,
            raw_output=str(final_state.get("raw_answer", ""))[:1000],
            reasoning=str(final_state.get("reasoning", ""))[:1000],
            rag_context=str(final_state.get("context", "") or final_state.get("rag_context", ""))[:1500],
        )

    def log_summary(self, metrics: Dict[str, float]) -> None:
        """Log aggregate metrics (accuracy, F1, coverage, …) to the run summary.

        Call this after all scenarios have been processed.

        Parameters
        ----------
        metrics : dict
            Example: ``{"accuracy": 0.87, "macro_f1": 0.85, "coverage": 1.0}``
        """
        if not self._enabled or self._run is None:
            return
        try:
            self._wandb.log(metrics)
            for k, v in metrics.items():
                self._run.summary[k] = v
        except Exception as exc:
            logger.debug("W&B log_summary failed: %s", exc)

    def finish(self) -> None:
        """Flush the final table snapshot and close the W&B run."""
        if not self._enabled or self._run is None:
            return
        try:
            with self._lock:
                self._flush_table()
            self._run.finish()
            logger.info("W&B run finished: %s", self._run.url)
        except Exception as exc:
            logger.warning("W&B finish failed: %s", exc)
        finally:
            # Prevent atexit / __del__ from calling finish() a second time.
            self._run = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_row(
        self,
        scenario_id: str,
        task_id: str,
        track: str,
        label: str,
        prediction: str,
        exact_match,
        status: str,
        elapsed_s: float,
        raw_output: str,
        reasoning: str,
        rag_context: str,
    ) -> None:
        """Append one row, emit per-step scalars, and flush table periodically."""
        with self._lock:
            self._step += 1
            idx = self._step
            row = [
                idx,
                scenario_id,
                task_id,
                track,
                label,
                prediction,
                exact_match,
                status,
                round(elapsed_s, 2),
                raw_output,
                reasoning,
                rag_context,
            ]
            self._rows.append(row)

            # Real-time scalar metrics (appear as line charts in W&B)
            scalars: Dict[str, Any] = {
                "latency/elapsed_s": elapsed_s,
                "agent/answer_len": len(prediction),
                "agent/is_empty": int(not prediction.strip()),
                "agent/is_error": int(status == "error"),
            }
            if exact_match is not None:
                scalars["eval/exact_match"] = int(exact_match)
                # Rolling accuracy (mean of all logged exact_match values)
                _em_vals = [r[6] for r in self._rows if r[6] is not None]
                if _em_vals:
                    scalars["eval/rolling_accuracy"] = sum(_em_vals) / len(_em_vals)

            try:
                self._wandb.log(scalars, step=idx)
            except Exception as exc:
                logger.debug("W&B scalar log failed: %s", exc)

            # Periodic table flush so the table is visible mid-run
            if idx == 1 or idx % self._flush_every == 0:
                self._flush_table()

    def _flush_table(self) -> None:
        """Rebuild the table from accumulated rows and log it.

        Must be called while ``self._lock`` is held (or at finish() time).
        wandb.Table is immutable after the first log call, so we always
        create a fresh Table object from the current row list.
        """
        if self._run is None or not self._rows:
            return
        try:
            snapshot = self._wandb.Table(
                columns=_TABLE_COLUMNS,
                data=self._rows,
            )
            self._wandb.log({"results_table": snapshot}, step=self._step)
        except Exception as exc:
            logger.debug("W&B table flush failed: %s", exc)
