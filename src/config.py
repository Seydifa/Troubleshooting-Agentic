"""
config.py — Centralised Settings

Reads configuration from environment variables (populated by .env via python-dotenv).
Provides a single ``settings`` singleton used throughout the project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class Settings:
    """All runtime configuration, sourced from environment variables."""

    # Runtime environment: "dev" → local vLLM, "prod" → OpenRouter
    env: str = field(default_factory=lambda: os.getenv("ENV", "dev"))

    # Tool server URL (Track A + B)
    tool_server_url: str = field(
        default_factory=lambda: os.getenv("TOOL_SERVER_URL", "http://localhost:8000")
    )

    # OpenRouter (prod LLM)
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    openrouter_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        )
    )

    # vLLM (dev LLM) — OpenAI-compatible API
    vllm_base_url: str = field(
        default_factory=lambda: os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    )
    vllm_api_key: str = field(
        default_factory=lambda: os.getenv("VLLM_API_KEY", "EMPTY")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "Qwen/Qwen3.5-35B-A3B")
    )
    parser_model_name: str = field(
        default_factory=lambda: os.getenv(
            "PARSER_MODEL_NAME",
            os.getenv("MODEL_NAME", "Qwen/Qwen3.5-35B-A3B"),
        )
    )

    # Competition / budget
    budget_limit: int = field(
        default_factory=lambda: int(os.getenv("BUDGET_LIMIT", "1000"))
    )

    # Data paths
    test_file_path: str = field(
        default_factory=lambda: os.getenv("TEST_FILE_PATH", "data/test.json")
    )
    output_csv_path: str = field(
        default_factory=lambda: os.getenv("OUTPUT_CSV_PATH", "result.csv")
    )

    # HuggingFace dataset access
    hf_token: str = field(default_factory=lambda: os.getenv("HF_TOKEN", ""))


settings = Settings()
