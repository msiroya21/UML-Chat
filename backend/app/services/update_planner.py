"""
Decides, on an update, which diagrams to (re)generate vs. carry forward unchanged.

- New types (requested but not present) -> generate.
- Existing types the update text targets (LLM intent classifier) -> regenerate (with prior IR).
- Existing requested types the update does NOT target -> carry forward untouched.
- Previously-present types the user dropped from the selection -> not included.

Failure of the classifier defaults to "targets nothing" — the safe choice, since it
carries good diagrams forward rather than risking a destructive regeneration.
"""
import logging
from typing import Dict, List, Set
from app.services.llm_client import invoke_with_fallback, extract_json

logger = logging.getLogger(__name__)

ACTION_GENERATE = "generate"
ACTION_REGENERATE = "regenerate"
ACTION_CARRY_FORWARD = "carry_forward"


def classify_update_targets(update_text: str, existing_types: List[str]) -> List[str]:
    """Return the subset of existing_types the update text intends to change."""
    if not existing_types:
        return []

    system = (
        "You route UML diagram update requests. Given the user's update instruction and the list of "
        "diagram types that already exist, decide which EXISTING types the instruction asks to change. "
        "Adding a brand-new type does not count as changing an existing one. "
        'Respond ONLY as JSON: {"targets": ["<type>", ...]} using only types from the provided list. '
        "If the instruction only adds new diagrams or is unrelated to the existing ones, return an empty list."
    )
    user = f"Existing types: {existing_types}\n\nUpdate instruction:\n{update_text}"

    try:
        response = invoke_with_fallback([("system", system), ("user", user)], temperature=0.0, json_mode=True)
        data = extract_json(response.content)
        targets = data.get("targets", [])
        result = [t for t in targets if t in existing_types]
        logger.info("Update classifier targets=%s (existing=%s)", result, existing_types)
        return result
    except Exception as e:
        logger.warning("Update classifier failed (%s); defaulting to no targets (carry-forward).", e)
        return []


def compute_update_actions(
    requested: List[str],
    prev_good_types: Set[str],
    targeted: Set[str],
) -> Dict[str, str]:
    """Map each requested diagram type to generate / regenerate / carry_forward."""
    actions: Dict[str, str] = {}
    for t in requested:
        if t not in prev_good_types:
            actions[t] = ACTION_GENERATE
        elif t in targeted:
            actions[t] = ACTION_REGENERATE
        else:
            actions[t] = ACTION_CARRY_FORWARD
    return actions
