"""Robust JSON extraction from LLM responses."""
import pytest
from app.services.llm_client import extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_with_surrounding_prose():
    assert extract_json('Sure, here you go:\n{"a": 1, "b": [2,3]}\nHope that helps!') == {"a": 1, "b": [2, 3]}


def test_nested_braces_bracket_matched():
    assert extract_json('prefix {"a": {"b": 1}} suffix') == {"a": {"b": 1}}


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no object here")


def test_top_level_array_extracts_first_object():
    # The model wrapped the IR in an array — we recover the first real object,
    # never returning a list (which used to crash validate_ir with .get()).
    result = extract_json('[{"diagram_type": "activity", "activities": []}]')
    assert isinstance(result, dict)
    assert result["diagram_type"] == "activity"


def test_bare_array_with_no_object_raises():
    with pytest.raises(ValueError):
        extract_json("[1, 2, 3]")
