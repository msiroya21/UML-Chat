import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from app.core.config import get_settings
from app.schemas.ir import IR_SCHEMA_MAP
from app.services.llm_client import invoke_with_fallback, extract_json, LLMConfigError

settings = get_settings()
logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Bumped when the system prompt / generation contract changes; stored as provenance
# on each Diagram so a feedback/training sample can be tied to what produced it.
PROMPT_VERSION = "2026-07-14"


class GenerationError(Exception):
    """
    Generation failed for a single diagram. Carries the model's best-effort output
    (partial_code) so the UI can show the REAL attempted PlantUML — never a fabricated
    example. Distinct from LLMConfigError (auth/config), which propagates separately.
    """
    def __init__(self, message: str, partial_code: Optional[str] = None):
        super().__init__(message)
        self.partial_code = partial_code


def _load_system_prompt() -> str:
    path = _PROMPTS_DIR / "system_prompt.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "You are a UML software architect. Respond ONLY with valid JSON matching the provided schema."


def _load_schema(diagram_type: str) -> dict:
    path = _PROMPTS_DIR / f"ir_schema_{diagram_type}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return IR_SCHEMA_MAP[diagram_type].model_json_schema()


def _load_few_shot(diagram_type: str) -> dict:
    path = _PROMPTS_DIR / "few_shot_examples" / f"{diagram_type}_example.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


# The 7 types below have no structured IR schema; the LLM emits PlantUML directly.
_PLANTUML_KEYWORD = {
    "object": "object",
    "package": "package",
    "composite_structure": "component",
    "communication": "sequence (communication style, numbered messages)",
    "interaction_overview": "activity (interaction overview)",
    "timing": "timing",
    "profile": "class (with stereotypes)",
}

_PLANTUML_SNIPPET = {
    "object": '@startuml\nobject "officer1 : ComplianceOfficer" as o1\nobject "circular42 : Circular" as c1\no1 --> c1 : reviews\n@enduml',
    "package": '@startuml\npackage "Web Layer" as web\npackage "Service Layer" as svc\npackage "Data Layer" as data\nweb ..> svc\nsvc ..> data\n@enduml',
    "composite_structure": '@startuml\ncomponent "ComplianceEngine" {\n  [Parser] as parser\n  [GapAnalyzer] as gap\n  parser --> gap\n}\n@enduml',
    "communication": '@startuml\nobject Officer\nobject Controller\nobject GapService\nOfficer -> Controller : 1: requestReview()\nController -> GapService : 2: analyze()\nGapService --> Controller : 3: gaps\n@enduml',
    "interaction_overview": '@startuml\nstart\n:ref Ingest Circular;\nif (gaps found?) then (yes)\n  :ref Raise Alert;\nelse (no)\n  :ref Archive;\nendif\nstop\n@enduml',
    "timing": '@startuml\nrobust "Ingestion Worker" as W\n@0\nW is Idle\n@100\nW is Parsing\n@300\nW is Idle\n@enduml',
    "profile": '@startuml\nclass "Circular" <<entity>>\nclass "IngestionService" <<microservice>>\nclass "PanNumber" <<PII>>\n@enduml',
}


def _sanitize_plantuml(text: str) -> str:
    """Strip fences and anything outside the first @startuml..@enduml block."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("@startuml")
    if start != -1:
        text = text[start:]
    end = text.rfind("@enduml")
    if end != -1:
        text = text[: end + len("@enduml")]
    return text.strip()


def _structurally_valid(code: str) -> bool:
    return code.startswith("@startuml") and code.endswith("@enduml") and len(code.split("\n")) >= 3


def _generate_plantuml_direct(diagram_type: str, prompt_context: str, prior_ir: Optional[dict]) -> Dict[str, Any]:
    title = diagram_type.replace("_", " ").title() + " Diagram"
    keyword = _PLANTUML_KEYWORD.get(diagram_type, diagram_type)
    snippet = _PLANTUML_SNIPPET.get(diagram_type)
    snippet_block = (
        f"\n\nMinimal valid syntax example (follow the structure, use the user's content):\n{snippet}"
        if snippet else ""
    )

    if prior_ir and prior_ir.get("_direct_plantuml"):
        instruction = (
            f"You are a PlantUML expert editing an EXISTING {diagram_type} diagram.\n"
            f"Current diagram:\n{prior_ir['_direct_plantuml']}\n\n"
            f"Apply the requested change and return the FULL updated PlantUML.\n"
            f"Output ONLY raw PlantUML starting with @startuml and ending with @enduml."
        )
    else:
        instruction = (
            f"You are a PlantUML expert. Generate a valid PlantUML {diagram_type} diagram using the "
            f"'{keyword}' syntax. Output ONLY raw PlantUML starting with @startuml and ending with "
            f"@enduml — no fences, no prose. Base it entirely on the user's requirements; do not copy "
            f"the example.{snippet_block}"
        )

    # LLMConfigError propagates (surfaced loudly by the orchestrator).
    try:
        response = invoke_with_fallback(
            [("system", instruction), ("user", f"Design requirements:\n{prompt_context}\n\nGenerate a {diagram_type} diagram.")],
            temperature=0.1,
        )
    except LLMConfigError:
        raise
    except Exception as e:
        raise GenerationError(f"LLM call failed for '{diagram_type}': {e}") from e

    code = _sanitize_plantuml(response.content)
    if not _structurally_valid(code):
        # Keep the model's real output so the UI can show it as code — never an example.
        raise GenerationError(f"Model did not return valid PlantUML for '{diagram_type}'.", partial_code=response.content)

    return {"diagram_type": diagram_type, "title": title, "_direct_plantuml": code}


def generate_ir(diagram_type: str, prompt_context: str, prior_ir: Optional[dict] = None) -> Dict[str, Any]:
    """
    Produce the IR for a diagram. For structured types returns validated-shape JSON IR;
    for direct types returns {"_direct_plantuml": code}. When prior_ir is given the model
    EDITS the existing structure (update/refine) instead of regenerating from scratch.

    Raises LLMConfigError (auth/config) or GenerationError (parse/other) — it never
    fabricates a few-shot example on failure.
    """
    if diagram_type not in IR_SCHEMA_MAP:
        return _generate_plantuml_direct(diagram_type, prompt_context, prior_ir)

    schema = _load_schema(diagram_type)
    few_shot = _load_few_shot(diagram_type)

    if prior_ir:
        system_instruction = (
            f"{_load_system_prompt()}\n\n"
            f"You are EDITING an existing '{diagram_type}' diagram IR. Current IR:\n"
            f"{json.dumps(prior_ir)}\n\n"
            f"Apply the requested change and return the FULL updated IR as JSON matching this schema:\n"
            f"{json.dumps(schema)}\n"
            f"Output ONLY the JSON object."
        )
    else:
        system_instruction = (
            f"{_load_system_prompt()}\n\n"
            f"Output a '{diagram_type}' diagram IR as JSON strictly following this schema:\n"
            f"{json.dumps(schema)}\n\n"
            f"Few-shot example (format reference only — do NOT copy its content):\n"
            f"Prompt: {few_shot.get('prompt', '')}\n"
            f"Output: {json.dumps(few_shot.get('ir', {}))}"
        )

    try:
        response = invoke_with_fallback(
            [("system", system_instruction), ("user", f"Design requirements:\n{prompt_context}")],
            temperature=0.1,
            json_mode=True,
        )
    except LLMConfigError:
        raise
    except Exception as e:
        raise GenerationError(f"LLM call failed for '{diagram_type}': {e}") from e

    try:
        return extract_json(response.content)
    except ValueError as e:
        raise GenerationError(f"Could not parse IR JSON for '{diagram_type}': {e}", partial_code=response.content) from e
