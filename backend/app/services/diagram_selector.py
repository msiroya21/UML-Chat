import logging
from typing import List, Optional
from app.core.config import get_settings
from app.services.llm_client import invoke_with_fallback, extract_json, LLMConfigError

settings = get_settings()
logger = logging.getLogger(__name__)

# All 14 UML 2.x types accepted by the API
ALL_ALLOWED_TYPES = {
    "sequence", "class", "component", "activity", "usecase", "state", "object",
    "deployment", "package", "composite_structure", "communication",
    "interaction_overview", "timing", "profile",
}

# Types with full structured-IR + deterministic code-generator support.
# Auto-select recommends only from these (the other 7 are opt-in via explicit chips).
SUPPORTED_TYPES = {
    "sequence", "class", "component",
    "activity", "usecase", "state", "deployment",
}


def select_diagrams(prompt: str, user_types: Optional[List[str]] = None) -> List[str]:
    # User-specified: pass through any that are in the full allowed set.
    # Unsupported types (outside SUPPORTED_TYPES) will fail gracefully in the orchestrator.
    if user_types:
        valid = [t for t in user_types if t in ALL_ALLOWED_TYPES]
        if valid:
            return valid

    # Auto-select: recommend only types with full IR support.
    try:
        system_instruction = (
            "You are a UML software architect. Choose UML diagram types from this list only: "
            '["sequence", "class", "component", "activity", "usecase", "state", "deployment"]. '
            "IMPORTANT: If the user explicitly names one or more diagram types in their description "
            "(e.g. 'draw an activity and deployment diagram'), return EXACTLY those types and nothing "
            "else — do not add any extras. Only when the user names no diagram types should you infer the "
            '2-4 most relevant. Respond ONLY as JSON: {"types": ["sequence", "class"]}.'
        )
        response = invoke_with_fallback(
            [("system", system_instruction), ("user", f"Design prompt:\n{prompt}")],
            temperature=0.0, json_mode=True,
        )
        selected = extract_json(response.content).get("types", [])
        valid = [t for t in selected if t in SUPPORTED_TYPES]
        if valid:
            return valid
    except LLMConfigError as e:
        logger.warning("Diagram selection skipped (config error: %s). Defaulting.", e)
    except Exception as e:
        logger.error("Diagram selection LLM call failed: %s", e)

    return ["sequence", "class"]
