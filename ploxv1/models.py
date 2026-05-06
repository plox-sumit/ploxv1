from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class ShellContext:
    cwd: str
    env: Dict[str, str]
    os_name: str = "linux"
    aws_profile: Optional[str] = None
    aws_region: Optional[str] = None


@dataclass
class ChatMessage:
    role: str
    content: str
    reasoning_details: Optional[Any] = None


@dataclass
class ModelConfig:
    backend: str  # "ollama" | "openrouter" | "claude" | "nvidia_nim"
    model_name: str
    api_key: Optional[str] = None
    nvidia_nim_url: Optional[str] = None  # custom NVIDIA NIM endpoint URL
    max_tokens: Optional[int] = None
    min_tokens: Optional[int] = None  # minimum tokens per response (>= 2000)
    timeout: Optional[int] = None  # seconds; None = wait indefinitely (best for slow NVIDIA NIM)


@dataclass
class LLMUsage:
    response_time_seconds: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass
class CommandPlan:
    domain: str
    action: str
    summary: str
    commands: List[str]
    requires_confirmation: bool = True
    resolved_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class CommandExecutionResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
