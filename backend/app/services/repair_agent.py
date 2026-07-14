import json
import logging
from typing import Dict, Any, List
from app.schemas.ir import IR_SCHEMA_MAP
from app.services.llm_client import invoke_with_fallback, extract_json, LLMConfigError

logger = logging.getLogger(__name__)


def repair_ir(
    diagram_type: str,
    prompt_context: str,
    broken_ir: Dict[str, Any],
    errors: List[str],
    attempt: int,
) -> Dict[str, Any]:
    """
    Feed validation/syntax errors back to the LLM to self-repair the IR JSON.
    Returns the repaired IR, or the original broken IR if repair is impossible
    (unsupported type, config error, or parse failure) — the caller re-validates.
    """
    if diagram_type not in IR_SCHEMA_MAP:
        return broken_ir

    schema = IR_SCHEMA_MAP[diagram_type].model_json_schema()
    errors_str = "\n".join(f"- {err}" for err in errors)

    system_instruction = (
        f"You are a UML software architect. A previously generated JSON IR for a '{diagram_type}' "
        f"diagram contains validation errors.\n\n"
        f"Correct the errors and output FIXED valid JSON matching this schema:\n{json.dumps(schema)}\n\n"
        f"Ensure all entity IDs in messages/relationships/dependencies refer to valid IDs.\n"
        f"Output ONLY the JSON object."
    )
    user_message = (
        f"Original Design Requirements:\n{prompt_context}\n\n"
        f"Broken IR JSON:\n{json.dumps(broken_ir)}\n\n"
        f"Validation Errors (Attempt {attempt}):\n{errors_str}\n\n"
        f"Output the corrected JSON IR:"
    )

    try:
        response = invoke_with_fallback(
            [("system", system_instruction), ("user", user_message)], temperature=0.1, json_mode=True
        )
        return extract_json(response.content)
    except LLMConfigError:
        # A config error will be surfaced by the primary generate path; don't crash the repair loop.
        logger.error("Repair skipped for '%s': LLM config error.", diagram_type)
        return broken_ir
    except Exception as e:
        logger.error("Self-repair failed (attempt %d) for '%s': %s", attempt, diagram_type, e)
        return broken_ir
