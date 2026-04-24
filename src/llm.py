"""
llm.py — Centralized LLM Factory

Single source of truth for all LangChain LLM instantiation.
Reads config from the ``settings`` singleton (src.config).

Two public factories:
- ``get_reasoning_llm()``  — analysis/reasoning agents (Qwen3 thinking mode)
- ``get_parser_llm()``     — JSON-only parsing agents (non-thinking, temperature=0)
"""

from __future__ import annotations

import os

from src.config import settings

# Fallback prod model when MODEL_NAME is not set in environment
_PROD_MODEL = "Qwen/Qwen3-235B-A22B"


def get_reasoning_llm():
    """Return the reasoning LLM based on ENV.

    - dev  → ChatOllama  (Qwen3 thinking mode: temp=0.6, top_p=0.95, top_k=20)
    - prod → ChatOpenAI  (OpenRouter, temp=0.3)
    """
    if settings.env == "prod":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("MODEL_NAME", _PROD_MODEL),
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            temperature=0.3,
        )
    else:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.model_name,
            base_url=settings.ollama_base_url,
            # Qwen3 thinking mode: temperature=0.6, top_p=0.95, top_k=20
            temperature=0.6,
            top_p=0.95,
            top_k=20,
        )


def get_parser_llm():
    """Return the parser LLM based on ENV.

    JSON-only agents — thinking mode disabled via /no_think in the prompt.

    - dev  → ChatOllama  (PARSER_MODEL_NAME, temperature=0 for determinism)
    - prod → ChatOpenAI  (OpenRouter, temperature=0, max_tokens=1024)
    """
    if settings.env == "prod":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("MODEL_NAME", _PROD_MODEL),
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            temperature=0,
            max_tokens=1024,
        )
    else:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.parser_model_name,
            base_url=settings.ollama_base_url,
            # Qwen3 non-thinking mode: temperature=0 for JSON determinism
            temperature=0,
        )
