from ploxv1.models import ChatMessage, CommandExecutionResult, CommandPlan, ShellContext
from ploxv1.prompting import build_prompt
from ploxv1.repair_prompting import OUTPUT_TAIL_CHARS, build_repair_prompt

CONTEXT = ShellContext(cwd="/home/user", os_name="linux")


def test_json_examples_use_single_braces():
    # The prompt is a plain string, so doubled braces would reach the model as they are.
    prompt = build_prompt("list files", CONTEXT, [])
    assert "{{" not in prompt and "}}" not in prompt


def test_history_is_listed_before_the_request():
    history = [ChatMessage("user", "list files"), ChatMessage("assistant", "[Ran: List files]\n$ ls\na.txt")]
    prompt = build_prompt("how many are there", CONTEXT, history)
    assert "user: list files" in prompt
    assert "a.txt" in prompt
    assert prompt.index("a.txt") < prompt.index("how many are there")


def test_aws_settings_are_shown():
    context = ShellContext(cwd="/", os_name="linux", aws_profile="dev", aws_region="ap-south-1")
    prompt = build_prompt("list buckets", context, [])
    assert "aws_profile: dev" in prompt
    assert "aws_region: ap-south-1" in prompt


def test_repair_prompt_keeps_only_the_end_of_a_long_output():
    failed = CommandExecutionResult(command="make", returncode=2, output="START " + "x" * 10000 + " the real error")
    prompt = build_repair_prompt("build it", CommandPlan(summary="Build", commands=["make"]), failed, CONTEXT)
    assert "the real error" in prompt
    assert "START" not in prompt
    assert len(prompt) < OUTPUT_TAIL_CHARS + 2000
