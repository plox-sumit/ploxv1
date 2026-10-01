from types import SimpleNamespace

import pytest

from ploxv1 import repl
from ploxv1.models import CommandExecutionResult, LLMUsage, ModelConfig


@pytest.fixture
def session(monkeypatch, capsys):
    """Run the REPL with typed input, model answers and the shell all scripted.

    session(inputs, answers, failing=()) feeds `inputs` to every prompt, hands out `answers` one
    per model call, and makes every command in `failing` exit with code 1. Nothing real runs.
    An exception in `answers` is raised instead of returned; KeyboardInterrupt in `inputs` is Ctrl+C.
    """

    def run(inputs, answers, failing=()):
        inputs, answers = list(inputs), list(answers)
        state = SimpleNamespace(ran=[], prompts=[], out="")

        def fake_input(_prompt=""):
            if not inputs:
                raise EOFError
            item = inputs.pop(0)
            if item is KeyboardInterrupt:
                raise KeyboardInterrupt
            return item

        def fake_ask(prompt, config, history):
            state.prompts.append(prompt)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer, None, LLMUsage(response_time_seconds=0.0)

        def fake_run_single_command(command):
            state.ran.append(command)
            code = 1 if command in failing else 0
            return CommandExecutionResult(command=command, returncode=code, stdout="", stderr="boom" if code else "")

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(repl, "ask_model_json", fake_ask)
        monkeypatch.setattr(repl, "ask_model_text", fake_ask)
        monkeypatch.setattr(repl, "run_single_command", fake_run_single_command)
        monkeypatch.setattr(repl, "spinner_start", lambda: None)
        monkeypatch.setattr(repl, "spinner_stop", lambda: None)

        repl.repl_loop(ModelConfig(backend="ollama", model_name="test"))
        state.out = capsys.readouterr().out
        return state

    return run


def plan(*commands, requires_confirmation=True):
    return {"commands": list(commands), "summary": "test plan", "requires_confirmation": requires_confirmation}
