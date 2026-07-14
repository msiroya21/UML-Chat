"""Deterministic IR -> PlantUML generation for every structured type."""
import json
import glob
import os
import pytest
from app.schemas.ir import IR_SCHEMA_MAP
from app.services.code_generator import ir_to_plantuml
from app.services.validator import validate_ir, validate_plantuml

_EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "prompts", "few_shot_examples")
_EXAMPLE_FILES = sorted(glob.glob(os.path.join(_EXAMPLES_DIR, "*_example.json")))


@pytest.mark.parametrize("path", _EXAMPLE_FILES, ids=[os.path.basename(p) for p in _EXAMPLE_FILES])
def test_few_shot_ir_generates_valid_plantuml(path):
    dtype = os.path.basename(path).replace("_example.json", "")
    ir = json.load(open(path, encoding="utf-8"))["ir"]

    ok, errs = validate_ir(dtype, ir)
    assert ok, f"few-shot IR for {dtype} failed validation: {errs}"

    code = ir_to_plantuml(dtype, ir)
    assert code.startswith("@startuml") and code.strip().endswith("@enduml")
    dsl_ok, dsl_errs = validate_plantuml(code)
    assert dsl_ok, f"generated PlantUML for {dtype} failed structural check: {dsl_errs}"


def test_all_seven_structured_types_have_generators():
    assert set(IR_SCHEMA_MAP) == {
        "sequence", "class", "component", "activity", "usecase", "state", "deployment",
    }


def test_direct_plantuml_passthrough():
    ir = {"diagram_type": "timing", "_direct_plantuml": "@startuml\nrobust A\n@enduml"}
    assert ir_to_plantuml("timing", ir) == ir["_direct_plantuml"]


def test_sequence_content_reflects_ir():
    ir = {
        "diagram_type": "sequence", "title": "T",
        "participants": [{"id": "a", "label": "Alice", "type": "actor"},
                         {"id": "b", "label": "Bob", "type": "participant"}],
        "messages": [{"from": "a", "to": "b", "label": "hi", "type": "sync", "order": 1}],
    }
    code = ir_to_plantuml("sequence", ir)
    assert "Alice" in code and "Bob" in code and "hi" in code


def test_quotes_in_labels_are_escaped():
    # A label containing a double quote must not break the quoted PlantUML label.
    ir = {
        "diagram_type": "sequence", "title": "T",
        "participants": [{"id": "a", "label": 'The "Boss"', "type": "actor"},
                         {"id": "b", "label": "Bob", "type": "participant"}],
        "messages": [{"from": "a", "to": "b", "label": "hi", "type": "sync", "order": 1}],
    }
    code = ir_to_plantuml("sequence", ir)
    assert '\\"Boss\\"' in code          # escaped, not a raw closing quote
    assert code.startswith("@startuml") and code.strip().endswith("@enduml")


def test_class_and_component_names_are_quoted():
    # Names with spaces must be quoted with an `as <id>` alias so relationships resolve.
    class_ir = {
        "diagram_type": "class", "title": "T",
        "classes": [{"id": "c1", "name": "Order Manager", "attributes": [], "methods": []}],
        "relationships": [],
    }
    assert 'class "Order Manager" as c1' in ir_to_plantuml("class", class_ir)

    comp_ir = {
        "diagram_type": "component", "title": "T",
        "components": [{"id": "svc", "name": "Drone Fleet Manager"}],
        "interfaces": [], "dependencies": [],
    }
    assert 'component "Drone Fleet Manager" as svc' in ir_to_plantuml("component", comp_ir)
