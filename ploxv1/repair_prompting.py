import json
from .models import ShellContext, CommandExecutionResult, CommandPlan

# The end of the output is where the error is, and a long log would swamp the prompt.
OUTPUT_TAIL_CHARS = 2000


def build_repair_prompt(
    original_user_input: str,
    failed_plan: CommandPlan,
    failed_result: CommandExecutionResult,
    context: ShellContext,
) -> str:
    plan_json = {
        "summary": failed_plan.summary,
        "commands": failed_plan.commands,
    }

    return f"""A command FAILED. You must fix it.

## What the user wanted
{original_user_input}

## The broken plan
{json.dumps(plan_json, indent=2)}

## The error
failed command: {failed_result.command}
returncode: {failed_result.returncode}
output: {failed_result.output.strip()[-OUTPUT_TAIL_CHARS:] or "(none)"}

## Environment
cwd: {context.cwd}
os: {context.os_name}

## Your job
Figure out why it failed (wrong OS command? typo? missing dependency? bad path?) and output a FIXED plan.

## Rules
- If the error is a typo → fix it
- If the error is wrong OS (Linux vs Windows) → use the correct commands for this OS
- Missing dep? → suggest an alternative approach, don't just try to install it
- NEVER repeat the exact same broken command
- If nothing can fix it, say why: {{"commands": [], "reply": "<why it can't be done>"}}

## Output format (JSON only, no markdown/backticks)
{{
  "commands": ["fixed_cmd1", "fixed_cmd2"],
  "summary": "Fixed: <one line description>",
  "requires_confirmation": true
}}

ONLY output JSON. No markdown. No backticks. No chat.
"""
