import os
import re
import shutil

# ── Cross-platform shell detection ──────────────────────────────────
IS_WINDOWS = os.name == "nt"


def find_shell() -> str | None:
    # WSL has powershell.exe on its PATH too, so pick by OS, not by what is installed.
    if IS_WINDOWS:
        return shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    return shutil.which("bash") or shutil.which("sh")


SHELL_PATH = find_shell()

# ── Dangerous command patterns ──────────────────────────────────────
# Searched anywhere in the command, so `ls && rm -rf x` is caught too.
DESTRUCTIVE_PATTERNS = [
    r"(?<!-)\brm\b", r"\brmdir\b", r"\bdel\b",
    r"\bmv\b",
    r"\bchmod\b", r"\bchown\b",
    r"\bsudo\b",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\bkill\b", r"\bkillall\b", r"\bpkill\b",
    r"\bdocker\b[^|;&]*\b(rmi|prune)\b",
    r"\bgit\s+(reset|clean)\b", r"\bgit\s+push\b[^|;&]*\s(--force|-f)\b",
    r"\bdd\b",
    r"\bmkfs\b", r"\btruncate\b", r"\bshred\b", r"\btee\b",
    r"\bfind\b[^|;&]*\s-(delete|exec|execdir|ok)\b",
    r"\bsed\b[^|;&]*\s(-\w*i\b|--in-place)",
    r"\|\s*(ba|z|da)?sh\b",
    r"\baws\s+(iam|s3\s+rb)\b",
    r"\baws\b[^|;&]*\b(delete|terminate|deregister|purge)\b",
    r"(?i:\b(Remove-Item|Clear-Content|Set-Content|Out-File|Stop-Process|Stop-Computer|Restart-Computer)\b)",
]

# Matched against each part of a pipeline or chain, from its first word.
SAFE_READ_ONLY = [
    r"^ls\b", r"^dir\b",
    r"^cat\b", r"^head\b", r"^tail\b", r"^less\b", r"^more\b",
    r"^echo\b", r"^printf\b",
    r"^whoami\b", r"^id\b", r"^groups\b",
    r"^pwd\b", r"^which\b", r"^type\b", r"^command\s+-[vV]\b",
    r"^date\b", r"^uptime\b", r"^uname\b", r"^hostname\b",
    r"^grep\b", r"^find\b", r"^locate\b",
    r"^ps\b",
    r"^df\b", r"^du\b", r"^free\b",
    r"^env$", r"^printenv\b",
    r"^awk\b", r"^sed\b",
    r"^sort\b", r"^uniq\b", r"^wc\b",
    r"^docker\s+(ps|images|logs|inspect|version|info)\b",
    r"^git\s+(status|log|diff|show)\b",
    r"^kubectl\s+(get|describe|logs)\b",
    r"^aws\s+s3\s+ls\b", r"^aws\s+sts\b", r"^aws\s+\S+\s+(describe|list|get)-",
    r"(?i:^Get-\w+)",
]

_QUOTED = r"'[^']*'|\"[^\"]*\""
# A `>` that writes to a file. `2>&1` and `> /dev/null` write nothing.
_FILE_REDIRECT = r">(?!>?\s*(&\d|/dev/null|\$null))"


def _clean(command: str) -> str:
    return command.strip().lstrip("$ ")


def is_destructive(command: str) -> bool:
    cmd = _clean(command)
    if re.search(_FILE_REDIRECT, re.sub(_QUOTED, "''", cmd)):
        return True
    return any(re.search(pattern, cmd) for pattern in DESTRUCTIVE_PATTERNS)


def is_read_only(command: str) -> bool:
    """True only when every part of the command is a known read-only command."""
    cmd = _clean(command)
    if is_destructive(cmd):
        return False
    # Escaped quotes and command substitution can hide a second command from the split below.
    if re.search(r"\\[\"']|\$\(|`", cmd):
        return False
    bare = re.sub(r"\d?>>?\s*(&\d|/dev/null|\$null)", "", re.sub(_QUOTED, "''", cmd))
    parts = [part.strip() for part in re.split(r"\|\||&&|[|;&\n]", bare)]
    return all(any(re.search(pattern, part) for pattern in SAFE_READ_ONLY) for part in parts if part)
