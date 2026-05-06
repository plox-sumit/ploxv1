import os
import re
import shutil

# ── Cross-platform shell detection ──────────────────────────────────
SHELL_PATH = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("bash") or shutil.which("sh")
IS_WINDOWS = os.name == "nt"

# ── Dangerous command patterns ──────────────────────────────────────
DESTRUCTIVE_PATTERNS = [
    r"\brm\b", r"\brmdir\b", r"\bdel\b",
    r"\bmv\b",
    r"\bchmod\b", r"\bchown\b",
    r"\bsudo\b",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\bkill\b", r"\bkillall\b", r"\bpkill\b",
    r"\bdocker\s+(rm|rmi|prune|system\s+prune)",
    r"\bgit\s+(reset|clean|push\s+--force)",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\b>:|>>",
    r"\baws\s+(iam|ec2\s+terminate|s3\s+rb|rds\s+delete|eks\s+delete|ecs\s+delete)",
    r"\baws\s+cloudformation\s+delete",
]

SAFE_READ_ONLY = [
    r"^ls\b", r"^dir\b",
    r"^cat\b", r"^head\b", r"^tail\b", r"^less\b", r"^more\b",
    r"^echo\b", r"^printf\b",
    r"^whoami\b", r"^id\b", r"^groups\b",
    r"^pwd\b", r"^which\b", r"^type\b", r"^command\b",
    r"^date\b", r"^uptime\b", r"^uname\b", r"^hostname\b",
    r"^grep\b", r"^find\b", r"^locate\b",
    r"^ps\b", r"^top\b", r"^htop\b",
    r"^df\b", r"^du\b", r"^free\b",
    r"^env\b", r"^printenv\b",
    r"^awk\b", r"^sed\b",
    r"^sort\b", r"^uniq\b", r"^wc\b",
    r"^wget\b", r"^curl\b",
    r"^aws\s+s3\s+ls\b", r"^aws\s+ec2\s+describe\b", r"^aws\s+.*\bdescribe\b",
    r"^aws\s+sts\b",
]


def is_destructive(command: str) -> bool:
    cmd_clean = command.strip().lstrip("$ ")

    # Check safe patterns first
    for pattern in SAFE_READ_ONLY:
        if re.search(pattern, cmd_clean):
            return False

    # Check destructive patterns
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, cmd_clean):
            return True

    # By default, be safe - require confirmation
    return False


def confirm_destructive(commands: list[str]) -> str:
    """Show the user what will run and get confirmation.
    Returns 'proceed', 'cancel', 'edit', or 'chat'."""
    destructive = [c for c in commands if is_destructive(c)]

    print(f"\n  ⚠  These commands will modify your system:")
    for cmd in commands:
        is_dest = is_destructive(cmd)
        marker = "⚠ DESTRUCTIVE" if is_dest else "✓ safe"
        color = "\033[91m" if is_dest else "\033[92m"
        print(f"    {color}[{marker}]\033[0m  $ {cmd}")

    if destructive:
        print(f"\n  ⚠  {len(destructive)} destructive command(s) detected.")
        print(f"  These may delete files, modify permissions, use sudo, or affect AWS resources.")

    return ""
