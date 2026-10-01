import os

import pytest

from ploxv1.llm import LLMError
from ploxv1.models import LLMUsage
from ploxv1.repl import MAX_REPAIRS, print_completion_block

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


# ── Errors that used to end the session with a traceback ──


def test_rejected_api_key_prints_help_instead_of_crashing(session):
    state = session([TASK], [LLMError("OpenRouter request failed: 401 Unauthorized", 401)])
    assert "Authentication failed" in state.out


def test_other_api_errors_are_shown(session):
    state = session([TASK], [LLMError("OpenRouter request failed: 500 Server Error", 500)])
    assert "500 Server Error" in state.out


def test_api_error_during_the_json_retry_is_shown(session):
    state = session([TASK], [{"error": "JSON parse failed", "raw": "hello"}, LLMError("server went away", 503)])
    assert "server went away" in state.out


def test_api_error_while_chatting_about_a_plan_is_shown(session):
    state = session([TASK, "c"], [plan("rm -rf build"), LLMError("server went away", 503)])
    assert "server went away" in state.out
    assert state.ran == []


def test_ctrl_c_at_the_confirm_prompt_drops_the_task_not_the_session(session):
    state = session([TASK, KeyboardInterrupt, "list the files", "y"], [plan("rm -rf build"), plan("ls")])
    assert "Interrupted" in state.out
    assert state.ran == ["ls"]


def test_commands_given_as_one_string_run_as_one_command(session):
    state = session(["list the files", "y"], [{"commands": "ls -la", "summary": "s"}])
    assert state.ran == ["ls -la"]


def test_commands_that_are_not_text_are_dropped(session):
    state = session(["list the files"], [{"commands": [{"cmd": "ls"}]}, {"commands": [None, 3]}])
    assert state.ran == []
    assert "Could not generate commands" in state.out


def test_token_line_copes_with_a_missing_count(capsys):
    print_completion_block(LLMUsage(response_time_seconds=1.0, input_tokens=None, output_tokens=42, total_tokens=42))
    assert "in: ? | out: 42" in capsys.readouterr().out


@pytest.mark.parametrize("command, lands_in", [
    ("cd ~", os.path.expanduser("~")),
    ("cd '~'", os.path.expanduser("~")),
    ("cd sub", "sub"),
    ('cd "sub"', "sub"),
    ("cd sub && ls", "."),
    ("cd nowhere", "."),
])
def test_cd_is_followed_when_it_can_be(session, tmp_path, monkeypatch, command, lands_in):
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    session(["go there", "y"], [plan(command)])
    assert os.path.samefile(os.getcwd(), tmp_path / lands_in)
