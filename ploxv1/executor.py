import os
import subprocess
from .models import CommandExecutionResult
from .safety import SHELL_PATH


def run_single_command(command: str) -> CommandExecutionResult:
    """Execute a single shell command safely using the correct shell for the OS."""
    shell_path = SHELL_PATH
    is_powershell = os.name == "nt"

    # Fallback if shell is not found
    if not shell_path or not os.access(shell_path, os.X_OK):
        shell_path = "powershell.exe" if is_powershell else "/bin/bash"

    # Ensure AWS_PAGER is unset to avoid interactive prompts
    env = os.environ.copy()
    env["AWS_PAGER"] = ""

    if is_powershell:
        args = [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        args = [shell_path, "-c", command]

    result = subprocess.run(
        args,
        shell=False,
        env=env,
        capture_output=True,
        text=True,
    )

    return CommandExecutionResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
