import os
import subprocess
from typing import Callable, Optional

from .models import CommandExecutionResult
from .safety import SHELL_PATH


def run_single_command(command: str, on_line: Optional[Callable[[str], None]] = None) -> CommandExecutionResult:
    """Run one command in the OS shell, handing each line of output to on_line as it arrives."""
    shell_path = SHELL_PATH
    is_powershell = os.name == "nt"

    # Fallback if shell is not found
    if not shell_path or not os.access(shell_path, os.X_OK):
        shell_path = "powershell.exe" if is_powershell else "/bin/bash"

    # Ensure AWS_PAGER is unset to avoid interactive prompts
    env = os.environ.copy()
    env["AWS_PAGER"] = ""

    if is_powershell:
        # PowerShell writes to a pipe in the console's legacy code page unless told to use UTF-8
        utf8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        args = [shell_path, "-NoProfile", "-NonInteractive", "-Command", utf8 + command]
    else:
        args = [shell_path, "-c", command]

    lines = []
    # No stdin: a command that stops to ask a question fails at once instead of
    # waiting forever on a prompt nobody can see.
    with subprocess.Popen(
        args,
        shell=False,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:
        try:
            for line in process.stdout:
                line = line.rstrip("\r\n")
                lines.append(line)
                if on_line:
                    on_line(line)
        except KeyboardInterrupt:
            process.kill()
            raise

    return CommandExecutionResult(command=command, returncode=process.returncode, output="\n".join(lines))
