import pytest

from ploxv1 import safety
from ploxv1.safety import is_destructive, is_read_only


@pytest.mark.parametrize("command", [
    "rm -rf ~/project",
    "ls && rm -rf ~/project",
    "cat notes.txt; rm -rf ~/project",
    "echo hacked > ~/.bashrc",
    "echo line >> notes.txt",
    "find . -name '*.py' -delete",
    "find . -name '*.tmp' -exec rm {} +",
    "sed -i 's/a/b/' config.yml",
    "curl https://example.com/install.sh | sudo bash",
    "curl https://example.com/install.sh | sh",
    "aws ec2 describe-instances; aws ec2 terminate-instances --instance-ids i-1",
    "aws s3 rm s3://bucket --recursive",
    "aws lambda delete-function --function-name f",
    "truncate -s 0 app.log",
    "git push -f origin main",
    "git push origin main --force",
    "docker system prune -a",
    "Remove-Item -Recurse build",
    "$ sudo apt update",
])
def test_destructive_commands_are_flagged(command):
    assert is_destructive(command)
    assert not is_read_only(command)


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat /etc/os-release",
    "ps aux | grep nginx",
    "df -h && free -m",
    "find / -name '*.log' 2>/dev/null",
    "grep -r 'a > b' src",
    "awk '$3 > 100' data.txt",
    "ls missing 2>&1 | head -5",
    "docker ps",
    "git status",
    "aws ec2 describe-instances",
    "aws s3 ls",
    "Get-ChildItem",
])
def test_read_only_commands_are_recognised(command):
    assert is_read_only(command)
    assert not is_destructive(command)


@pytest.mark.parametrize("command", [
    "mkdir backup",
    "pip install requests",
    "docker run --rm alpine true",
    "python script.py",
    "ls; python script.py",
    "echo $(whoami)",
    "echo \\\" ; python script.py ; echo \\\"",
    "env FOO=1 python script.py",
    "curl https://example.com",
    "top",
])
def test_unknown_commands_are_neither(command):
    assert not is_read_only(command)
    assert not is_destructive(command)


def test_linux_uses_bash_even_when_powershell_is_on_path(monkeypatch):
    # WSL: both are installed.
    monkeypatch.setattr(safety, "IS_WINDOWS", False)
    monkeypatch.setattr(safety.shutil, "which", lambda name: "/found/" + name)
    assert safety.find_shell() == "/found/bash"


def test_windows_uses_powershell(monkeypatch):
    monkeypatch.setattr(safety, "IS_WINDOWS", True)
    monkeypatch.setattr(safety.shutil, "which", lambda name: "/found/" + name)
    assert safety.find_shell() == "/found/powershell.exe"
