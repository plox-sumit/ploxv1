import os
import time

import pytest

from ploxv1.executor import run_single_command

# These run real, harmless commands in the machine's shell (bash or PowerShell).


def test_output_and_exit_code_are_returned():
    result = run_single_command("echo hello")
    assert result.returncode == 0
    assert result.output == "hello"


def test_lines_are_handed_over_as_they_arrive():
    seen = []
    run_single_command("echo one; echo two", on_line=seen.append)
    assert seen == ["one", "two"]


def test_failure_keeps_the_exit_code():
    assert run_single_command("exit 3").returncode == 3


def test_error_text_is_part_of_the_output():
    result = run_single_command("ls /no/such/folder/here")
    assert result.returncode != 0
    assert result.output.strip()


def test_non_ascii_output_survives():
    assert run_single_command("echo café").output == "café"


@pytest.mark.skipif(os.name == "nt", reason="uses cat")
def test_a_command_that_waits_for_typing_returns_at_once():
    # `cat` with no file reads the keyboard. With no keyboard attached it ends straight away.
    assert run_single_command("cat").returncode == 0


def test_ctrl_c_stops_the_command():
    def press_ctrl_c(line):
        raise KeyboardInterrupt

    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_single_command("echo started; sleep 30", on_line=press_ctrl_c)
    assert time.monotonic() - started < 15
