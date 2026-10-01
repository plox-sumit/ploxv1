from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ShellContext:
    cwd: str
    os_name: str = "linux"
    aws_profile: Optional[str] = None
    aws_region: Optional[str] = None


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ModelConfig:
    backend: str  # "ollama" | "openrouter" | "claude" | "nvidia_nim"
    model_name: str
    api_key: Optional[str] = None
    nvidia_nim_url: Optional[str] = None  # custom NVIDIA NIM endpoint URL
    max_tokens: Optional[int] = None  # None = leave it to the backend
    timeout: Optional[int] = None  # seconds; None = wait indefinitely (best for slow NVIDIA NIM)


@dataclass
class LLMUsage:
    response_time_seconds: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass
class CommandPlan:
    summary: str
    commands: List[str]
    requires_confirmation: bool = True


@dataclass
class CommandExecutionResult:
    command: str
    returncode: int
    output: str  # stdout and stderr together, in the order they were printed
