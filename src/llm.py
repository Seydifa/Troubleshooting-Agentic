"""
llm.py — Centralized LLM Factory

Single source of truth for all LangChain LLM instantiation.
Reads config from the ``src.config`` module (accessed dynamically so that
notebook Cell 4 setting patches are always visible).

Two public factories:
- ``get_reasoning_llm()``  — analysis/reasoning agents (Qwen3.5 thinking mode)
- ``get_parser_llm()``     — JSON-only parsing agents (non-thinking, temperature=0)

Both functions return a **module-level singleton** — the same instance is
shared across all agents so Ollama maintains a single connection pool and the
Python overhead of repeated object creation is eliminated.

Call ``clear_llm_cache()`` after changing settings (e.g. switching ENV) to
force re-initialisation on the next call.
"""

from __future__ import annotations

import os
from typing import Any

import src.config as _config  # module reference — sees live settings patches

# Competition model — Qwen3.5-35B-A3B (mandatory, no substitution allowed)
_PROD_MODEL = "Qwen/Qwen3.5-35B-A3B"

# Module-level singletons — shared by every agent
_reasoning_llm: Any = None
_parser_llm: Any = None


def get_reasoning_llm() -> Any:
    """Return the shared reasoning LLM (lazy-initialised singleton).

    - dev  → ChatOllama  (Qwen3.5: temp=0.6, top_p=0.95, top_k=20)
    - prod → ChatOpenAI  (OpenRouter, temp=0.3)
    """
    global _reasoning_llm
    if _reasoning_llm is None:
        if _config.settings.env == "prod":
            from langchain_openai import ChatOpenAI

            _reasoning_llm = ChatOpenAI(
                model=os.getenv("MODEL_NAME", _PROD_MODEL),
                base_url=_config.settings.openrouter_base_url,
                api_key=_config.settings.openrouter_api_key,
                temperature=0.3,
            )
        else:
            from langchain_ollama import ChatOllama

            _reasoning_llm = ChatOllama(
                model=_config.settings.model_name,
                base_url=_config.settings.ollama_base_url,
                # Disable Qwen3.5 extended thinking at the API level
                think=False,
                temperature=0.6,
                top_p=0.95,
                top_k=20,
            )
    return _reasoning_llm


def get_parser_llm() -> Any:
    """Return the shared parser LLM (lazy-initialised singleton).

    JSON-only agents — thinking mode disabled via think=False.

    - dev  → ChatOllama  (PARSER_MODEL_NAME, temperature=0 for determinism)
    - prod → ChatOpenAI  (OpenRouter, temperature=0, max_tokens=1024)
    """
    global _parser_llm
    if _parser_llm is None:
        if _config.settings.env == "prod":
            from langchain_openai import ChatOpenAI

            _parser_llm = ChatOpenAI(
                model=os.getenv("MODEL_NAME", _PROD_MODEL),
                base_url=_config.settings.openrouter_base_url,
                api_key=_config.settings.openrouter_api_key,
                temperature=0,
                max_tokens=1024,
            )
        else:
            from langchain_ollama import ChatOllama

            _parser_llm = ChatOllama(
                model=_config.settings.parser_model_name,
                base_url=_config.settings.ollama_base_url,
                # Qwen3.5 non-thinking mode: temperature=0 for JSON determinism
                temperature=0,
            )
    return _parser_llm


def clear_llm_cache() -> None:
    """Force both singletons to be re-created on the next call.

    Call this after patching ``src.config.settings`` (e.g. in notebook Cell 4
    when switching between dev and prod environments).
    """
    global _reasoning_llm, _parser_llm
    _reasoning_llm = None
    _parser_llm = None
