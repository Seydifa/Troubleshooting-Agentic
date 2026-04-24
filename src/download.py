"""
Download the Telco Troubleshooting Agentic Challenge dataset from HuggingFace.

The dataset is gated — your HF_TOKEN must be set in .env and you must have
accepted the dataset terms at:
  https://huggingface.co/datasets/netop/Telco-Troubleshooting-Agentic-Challenge

Usage (from the project root):
    python src/download.py

Or via main.py:
    python src/main.py --download
"""

import sys
from pathlib import Path

# ── project root on path so `src.config` is importable ──────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huggingface_hub import snapshot_download
from huggingface_hub.utils import HfHubHTTPError

from src.config import settings

REPO_ID = "netop/Telco-Troubleshooting-Agentic-Challenge"
LOCAL_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def download() -> Path:
    token = settings.hf_token
    if not token:
        raise EnvironmentError(
            "HF_TOKEN is not set. Add it to your .env file and re-run."
        )

    print(f"Downloading {REPO_ID} → {LOCAL_DIR} …")
    try:
        path = snapshot_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            local_dir=str(LOCAL_DIR),
            token=token,
            ignore_patterns=[
                "*.bin",
                "*.safetensors",
            ],  # skip heavy model shards if any
        )
    except HfHubHTTPError as exc:
        if "403" in str(exc):
            raise PermissionError(
                "Access denied. Accept the dataset terms at "
                f"https://huggingface.co/datasets/{REPO_ID} then retry."
            ) from exc
        raise

    print(f"Download complete: {path}")
    return Path(path)


if __name__ == "__main__":
    download()
