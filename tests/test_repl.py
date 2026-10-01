import pytest

from ploxv1.repl import MAX_REPAIRS

from .conftest import plan

TASK = "remove the build folder"


@pytest.mark.parametrize("answer", ["", "wait", "nn", "q", "n"])
def test_only_a_clear_yes_runs_the_plan(session, answer):
    state = session([TASK, answer], [plan("rm -rf build")])
    assert state.ran == []


@pytest.mark.parametrize("answer", ["y", "yes", "Y"])
def test_yes_runs_the_plan(session, answer):
    state = session([TASK, answer], [plan("rm -rf build")])
    assert state.ran == ["rm -rf build"]


def test_edit_changes_the_command_without_asking_the_model_again(session):
    state = session(["list the files", "e", "0", "ls -la", "y"], [plan("ls", requires_confirmation=False)])
    assert state.ran == ["ls -la"]
    assert len(state.prompts) == 1


def test_model_cannot_label_a_destructive_plan_safe(session):
    state = session([TASK, "n"], [plan("rm -rf build", requires_confirmation=False)])
    assert "DESTRUCTIVE" in state.out
    assert "✓ SAFE" not in state.out


def test_read_only_plan_is_labelled_safe(session):
    state = session(["list the files", "n"], [plan("ls -la", requires_confirmation=False)])
    assert "✓ SAFE" in state.out


def test_editing_a_safe_plan_into_a_destructive_one_changes_the_label(session):
    state = session(["list the files", "e", "0", "rm -rf build", "n"], [plan("ls", requires_confirmation=False)])
    assert "DESTRUCTIVE" in state.out
    assert state.ran == []


def test_yes_to_all_still_asks_before_a_destructive_repair(session):
    state = session(
        ["list the files", "a", "n"],
        [plan("ls missing"), plan("rm -rf build")],
        failing=["ls missing"],
    )
    assert state.ran == ["ls missing"]


def test_yes_to_all_stops_repairing_after_the_limit(session):
    plans = [plan(f"ls missing{i}") for i in range(MAX_REPAIRS + 1)]
    state = session(["list the files", "a"], plans, failing=[p["commands"][0] for p in plans])
    assert len(state.prompts) == MAX_REPAIRS + 1
    assert len(state.ran) == MAX_REPAIRS + 1


def test_declining_a_repair_stops_the_task(session):
    state = session(["list the files", "y", "n"], [plan("ls missing")], failing=["ls missing"])
    assert len(state.prompts) == 1


def test_declining_a_second_repair_stops_the_task(session):
    state = session(
        ["list the files", "y", "y", "y", "n"],
        [plan("ls missing"), plan("ls missing2")],
        failing=["ls missing", "ls missing2"],
    )
    assert len(state.prompts) == 2
    assert state.ran == ["ls missing", "ls missing2"]
