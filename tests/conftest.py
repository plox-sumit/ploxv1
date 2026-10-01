from types import SimpleNamespace

import pytest

from ploxv1 import repl
from ploxv1.models import CommandExecutionResult, LLMUsage, ModelConfig


@pytest.fixture
def session(monkeypatch, capsys):
    """Run the REPL with typed input, model answers and the shell all scripted.

    session(inputs, answers, failing=(), output="") feeds `inputs` to every prompt, hands out
    `answers` one per model call, makes every command in `failing` exit with code 1 and every
    command print `output`. Nothing real runs.
    An exception in `answers` is raised instead of returned; KeyboardInterrupt in `inputs` is Ctrl+C.
    """

    def run(inputs, answers, failing=(), output=""):
        inputs, answers = list(inputs), list(answers)
        state = SimpleNamespace(ran=[], prompts=[], out="")

        def fake_input(_prompt=""):
            if not inputs:
                raise EOFError
            item = inputs.pop(0)
            if item is KeyboardInterrupt:
                raise KeyboardInterrupt
            return item

        def fake_ask(prompt, config):
            state.prompts.append(prompt)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer, None, LLMUsage(response_time_seconds=0.0)

        def fake_run_single_command(command, on_line=None):
            state.ran.append(command)
            code = 1 if command in failing else 0
            printed = "boom" if code else output
            if printed and on_line:
                on_line(printed)
            return CommandExecutionResult(command=command, returncode=code, output=printed)

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


def reply(text):
    return {"commands": [], "reply": text}
