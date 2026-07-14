"""IR referential-integrity and PlantUML structural validation."""
from app.services.validator import validate_ir, validate_plantuml


def test_sequence_rejects_dangling_message_endpoint():
    ir = {
        "diagram_type": "sequence", "title": "T",
        "participants": [{"id": "a", "label": "A", "type": "actor"}],
        "messages": [{"from": "a", "to": "ghost", "label": "x", "type": "sync", "order": 1}],
    }
    ok, errs = validate_ir("sequence", ir)
    assert not ok and any("ghost" in e for e in errs)


def test_class_rejects_dangling_relationship():
    ir = {
        "diagram_type": "class", "title": "T",
        "classes": [{"id": "c1", "name": "C1"}],
        "relationships": [{"from": "c1", "to": "missing", "type": "association"}],
    }
    ok, errs = validate_ir("class", ir)
    assert not ok


def test_activity_requires_start_node():
    ir = {
        "diagram_type": "activity", "title": "T",
        "nodes": [{"id": "n1", "type": "action", "label": "do"}],
        "edges": [],
    }
    ok, errs = validate_ir("activity", ir)
    assert not ok and any("start" in e.lower() for e in errs)


def test_direct_plantuml_dict_is_always_valid():
    ok, errs = validate_ir("timing", {"_direct_plantuml": "@startuml\nA\n@enduml"})
    assert ok and errs == []


def test_validate_plantuml_structural():
    assert validate_plantuml("@startuml\nA -> B\n@enduml")[0]
    assert not validate_plantuml("A -> B")[0]  # missing tags
    # trailing content after @enduml is tolerated (planner truncates, validator is lenient)
    assert validate_plantuml("@startuml\nA -> B\n@enduml\n")[0]
