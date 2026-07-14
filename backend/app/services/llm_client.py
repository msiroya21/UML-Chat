"""
Single entry point for all LLM calls (planner, repair, selector, update classifier,
title generator). Centralizes the model-fallback loop and a small error taxonomy so a
dead API key is surfaced loudly instead of masquerading as a fallback diagram.
"""
import json
import logging
import re
from typing import Any, List, Tuple
from langchain_groq import ChatGroq
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class LLMConfigError(Exception):
    """Non-retryable: missing/invalid API key or auth/permission failure. Surface to the user."""


class LLMUnavailableError(Exception):
    """Retryable exhausted: all models returned transient errors (503/429/capacity)."""


def _is_auth_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(t in s for t in (
        "401", "403", "invalid api key", "api key not valid", "unauthorized",
        "permission denied", "authentication",
    ))


def _is_transient_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(t in s for t in (
        "503", "429", "over capacity", "rate limit", "timeout", "temporarily unavailable",
        "service unavailable",
    ))


# Reuse ChatGroq clients instead of constructing one (and its HTTP client) per call.
# Keyed by the only params that change the client: (model, temperature, json_mode).
_clients: dict = {}


def _get_client(model: str, temperature: float, json_mode: bool) -> ChatGroq:
    key = (model, round(temperature, 3), json_mode)
    client = _clients.get(key)
    if client is None:
        kwargs: dict = {}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        client = ChatGroq(api_key=settings.GROQ_API_KEY, model=model, temperature=temperature, **kwargs)
        _clients[key] = client
    return client


def _invoke_one(model: str, messages: List[Tuple[str, str]], temperature: float, json_mode: bool) -> Any:
    try:
        return _get_client(model, temperature, json_mode).invoke(messages)
    except Exception as e:
        # Some models reject JSON mode — retry once without it (the robust parser handles the rest).
        if json_mode and ("response_format" in str(e).lower() or "json" in str(e).lower()):
            logger.warning("Model %s rejected json mode; retrying without it.", model)
            return _get_client(model, temperature, False).invoke(messages)
        raise


def invoke_with_fallback(messages: List[Tuple[str, str]], *, temperature: float = 0.1, json_mode: bool = False) -> Any:
    """
    Invoke the primary model, falling back through LLM_FALLBACK_MODELS on transient
    errors only. Raises LLMConfigError for auth/config problems (do NOT mask these),
    LLMUnavailableError if every model is transiently unavailable.
    """
    if not settings.GROQ_API_KEY:
        raise LLMConfigError("GROQ_API_KEY is not set")

    models = [settings.LLM_MODEL] + list(settings.LLM_FALLBACK_MODELS)
    last_exc: Exception | None = None
    for model in models:
        try:
            return _invoke_one(model, messages, temperature, json_mode)
        except Exception as e:
            if _is_auth_error(e):
                raise LLMConfigError(f"LLM auth/config error: {e}") from e
            if _is_transient_error(e):
                logger.warning("Model %s transient error (%s); trying next fallback.", model, e)
                last_exc = e
                continue
            # Non-transient, non-auth (e.g. bad request) — don't burn the whole fallback chain.
            raise
    raise LLMUnavailableError(f"All models exhausted; last error: {last_exc}") from last_exc


def extract_json(content: str) -> dict:
    """
    Robustly extract a JSON object from an LLM response: strip markdown fences, then
    bracket-match the first balanced {...}. Raises ValueError if none is parseable.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    # A bare object is the happy path. A non-dict (e.g. the model wrapped the IR in a
    # top-level array) falls through to bracket-matching the first real object below.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(text[start:i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("Extracted JSON is not an object")
                return obj
    raise ValueError("Unbalanced JSON object in LLM response")
