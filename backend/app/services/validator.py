import logging
from typing import Tuple, List, Dict, Any
from pydantic import ValidationError
from app.schemas.ir import IR_SCHEMA_MAP
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

def validate_ir(diagram_type: str, ir_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate the structured JSON IR using Pydantic schemas and semantic rules.
    Direct-PlantUML dicts (from unsupported types) are always valid.
    """
    if not isinstance(ir_dict, dict):
        # e.g. the model returned a JSON array — treat as a normal validation failure
        # so it routes into repair / graceful fallback instead of crashing the pipeline.
        return False, ["IR was not a JSON object"]

    if ir_dict.get("_direct_plantuml"):
        return True, []

    if diagram_type not in IR_SCHEMA_MAP:
        return False, [f"Unsupported diagram type: '{diagram_type}'"]
        
    model_class = IR_SCHEMA_MAP[diagram_type]
    try:
        model_class.model_validate(ir_dict)
        return True, []
    except ValidationError as e:
        errors = []
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            msg = error["msg"]
            errors.append(f"[{loc}]: {msg}")
        return False, errors
    except ValueError as e:
        return False, [str(e)]

def validate_plantuml(plantuml_code: str) -> Tuple[bool, List[str]]:
    """
    Basic structural validation of PlantUML DSL: the block must contain an
    @startuml/@enduml pair and at least one line of content between them.
    (The direct-PlantUML path already truncates to a clean block, so we accept
    any trailing whitespace rather than requiring a strict endswith.)
    """
    code = plantuml_code.strip()
    if "@startuml" not in code or "@enduml" not in code:
        return False, ["PlantUML code must contain '@startuml' and '@enduml'"]
    if code.index("@startuml") > code.rindex("@enduml"):
        return False, ["'@startuml' must appear before '@enduml'"]

    lines = [line.strip() for line in code.split("\n") if line.strip()]
    if len(lines) < 3:
        return False, ["PlantUML diagram is empty or trivial"]

    return True, []
