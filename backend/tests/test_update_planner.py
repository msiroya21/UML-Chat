"""The update diff — pure logic, no LLM."""
from app.services.update_planner import (
    compute_update_actions, ACTION_GENERATE, ACTION_REGENERATE, ACTION_CARRY_FORWARD,
)


def test_add_new_type_only_generates_new_and_carries_rest():
    actions = compute_update_actions(
        requested=["sequence", "class", "component"],
        prev_good_types={"sequence", "class"},
        targeted=set(),  # "add a component" targets nothing existing
    )
    assert actions == {
        "sequence": ACTION_CARRY_FORWARD,
        "class": ACTION_CARRY_FORWARD,
        "component": ACTION_GENERATE,
    }


def test_refine_regenerates_only_targeted():
    actions = compute_update_actions(
        requested=["sequence", "class"],
        prev_good_types={"sequence", "class"},
        targeted={"sequence"},  # "make the sequence async"
    )
    assert actions["sequence"] == ACTION_REGENERATE
    assert actions["class"] == ACTION_CARRY_FORWARD


def test_previously_failed_type_regenerates_from_scratch():
    # class was not a "good" prior diagram -> treat as generate, not carry_forward
    actions = compute_update_actions(
        requested=["class"],
        prev_good_types=set(),
        targeted=set(),
    )
    assert actions["class"] == ACTION_GENERATE


def test_deselected_type_is_dropped():
    actions = compute_update_actions(
        requested=["sequence"],
        prev_good_types={"sequence", "class"},
        targeted=set(),
    )
    assert "class" not in actions


def test_empty_requested_yields_no_actions():
    # Contract check: an empty request produces no work here. The orchestrator is
    # responsible for defaulting an empty update to the previous turn's types before
    # this is called, so a real empty update never reaches this as {}.
    assert compute_update_actions(requested=[], prev_good_types={"sequence"}, targeted=set()) == {}
