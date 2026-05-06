import json
from .models import ShellContext, CommandExecutionResult, CommandPlan


def build_repair_prompt(
    original_user_input: str,
    failed_plan: CommandPlan | None,
    failed_result: CommandExecutionResult | None,
    context: ShellContext,
) -> str:
    plan_json = {"error": "no plan available"}
    if failed_plan is not None:
        plan_json = {
            "summary": failed_plan.summary,
            "commands": failed_plan.commands,
        }

    result_json = {"returncode": -1, "stderr": "(none)", "stdout": "(none)"}
    if failed_result is not None:
        result_json = {
            "returncode": failed_result.returncode,
            "stderr": failed_result.stderr.strip() or "(none)",
            "stdout": failed_result.stdout.strip() or "(none)",
        }

    return f"""A command FAILED. You must fix it.

## What the user wanted
{original_user_input}

## The broken plan
{json.dumps(plan_json, indent=2)}

## The error
returncode: {result_json["returncode"]}
stderr: {result_json["stderr"]}
stdout: {result_json["stdout"]}

## Your job
Figure out why it failed (wrong OS command? typo? missing dependency? bad path?) and output a FIXED plan.

## Rules
- If the error is a typo → fix it
- If the error is wrong OS (Linux vs Windows) → use the correct commands for this OS
- Missing dep? → suggest an alternative approach, don't just try to install it
- NEVER repeat the exact same broken command
- NEVER give up — always find another approach

## Output format (JSON only, no markdown/backticks)
{{
  "commands": ["fixed_cmd1", "fixed_cmd2"],
  "summary": "Fixed: <one line description>",
  "requires_confirmation": true,
  "analysis": "Root cause: <why the original failed>"
}}

ONLY output JSON. No markdown. No backticks. No chat.
"""