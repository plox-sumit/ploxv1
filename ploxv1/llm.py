import json
import re
import time
import requests
import anthropic
from .models import ModelConfig, ChatMessage, LLMUsage

OLLAMA_URL = "http://localhost:11434/api/generate"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NVIDIA_NIM_DEFAULT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


# ── Retry decorator for transient API failures ──────────────────────
import functools

def _with_retry(func, *, max_retries=3, base_delay=2.0):
    """Decorator: retry on 429 and certain transient errors with exponential backoff."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except RuntimeError as e:
                err_text = str(e)
                # 429 rate limit OR timeout OR 503/502 service unavailable
                if ("429" in err_text or "rate" in err_text.lower() or
                    "timeout" in err_text.lower() or "timed out" in err_text.lower() or
                    "503" in err_text or "502" in err_text or "Bad gateway" in err_text or
                    "connection" in err_text.lower()):
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        print(f"  [Rate limited / server busy. Retrying in {delay:.0f}s... ({attempt+1}/{max_retries})]", flush=True)
                        time.sleep(delay)
                        continue
                raise
    return wrapper


def strip_code_fences(text: str) -> str:
    text = text.strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    elif text.startswith("```"):
        text = text[len("```"):].strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    return text


def _extract_json_from_text(raw: str) -> dict:
    """Try hard to extract valid JSON from a model response that might have extra text."""
    cleaned = strip_code_fences(raw)

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find the first complete JSON object (balanced braces)
    # Count nested depth to handle {"key": {"nested": "value"}} correctly
    start_idx = cleaned.find("{")
    if start_idx >= 0:
        depth = 0
        escaped = False
        in_string = False
        for i, ch in enumerate(cleaned[start_idx:], start=start_idx):
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_string:
                escaped = True
                continue
            if ch == '"' and not escaped:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start_idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # malformed, fall through to error

    # Last resort: model is clearly chatting, not giving JSON
    return {"error": "JSON parse failed", "raw": raw}


def _build_openai_messages(system_prompt: str, user_content: str, history: list[ChatMessage]) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_content})
    return messages


# ── Ollama ──────────────────────────────────────────────────────────
def _ask_ollama_raw(prompt: str, model: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    started = time.perf_counter()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if config.max_tokens:
        payload["options"] = {"num_predict": config.max_tokens}

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=config.timeout or None)
        response.raise_for_status()
        data = response.json()

        ended = time.perf_counter()
        usage = LLMUsage(
            response_time_seconds=ended - started,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            total_tokens=(
                (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
                if data.get("prompt_eval_count") is not None or data.get("eval_count") is not None
                else None
            ),
        )
        return data.get("response", "").strip(), None, usage
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}")

ask_ollama = _with_retry(_ask_ollama_raw, max_retries=3, base_delay=1.0)


# ── OpenRouter ──────────────────────────────────────────────────────
def _ask_openrouter_raw(messages: list[dict], model: str, api_key: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": messages,
    }
    if config.max_tokens:
        payload["max_tokens"] = config.max_tokens
    if config.min_tokens:
        payload["min_tokens"] = config.min_tokens

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config.timeout or None,
        )
        response.raise_for_status()
        data = response.json()

        ended = time.perf_counter()
        choice = data["choices"][0]
        content = choice["message"].get("content", "").strip()
        usage_data = data.get("usage", {})

        reasoning_details = choice["message"].get("reasoning_details")
        usage = LLMUsage(
            response_time_seconds=ended - started,
            input_tokens=usage_data.get("prompt_tokens"),
            output_tokens=usage_data.get("completion_tokens"),
            total_tokens=usage_data.get("total_tokens"),
        )
        return content, reasoning_details, usage
    except requests.RequestException as e:
        raise RuntimeError(f"OpenRouter request failed: {e}")

ask_openrouter = _with_retry(_ask_openrouter_raw, max_retries=3, base_delay=2.0)


# ── Anthropic Claude ────────────────────────────────────────────────
def _ask_claude_raw(messages: list[dict], model: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    started = time.perf_counter()
    client = anthropic.Anthropic(timeout=config.timeout or 600, max_retries=2)

    system_msg = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            user_messages.append(m)

    kwargs = {
        "model": model,
        "system": system_msg,
        "messages": user_messages,
    }
    if config.max_tokens:
        kwargs["max_tokens"] = config.max_tokens
    else:
        kwargs["max_tokens"] = 16384

    try:
        resp = client.messages.create(**kwargs)

        ended = time.perf_counter()
        content = ""
        reasoning_details = None
        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "thinking":
                content += block.thinking
            elif block.type == "redacted_thinking":
                reasoning_details = "redacted"

        usage = LLMUsage(
            response_time_seconds=ended - started,
            input_tokens=resp.usage.input_tokens if resp.usage else None,
            output_tokens=resp.usage.output_tokens if resp.usage else None,
            total_tokens=(
                resp.usage.input_tokens + resp.usage.output_tokens
                if resp.usage and resp.usage.input_tokens and resp.usage.output_tokens
                else None
            ),
        )
        return content.strip(), reasoning_details, usage
    except anthropic.AnthropicError as e:
        raise RuntimeError(f"Anthropic request failed: {e}")

ask_claude = _with_retry(_ask_claude_raw, max_retries=3, base_delay=2.0)


# ── NVIDIA NIM ──────────────────────────────────────────────────────
def _ask_nvidia_nim_raw(messages: list[dict], model: str, api_key: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    """
    Call NVIDIA NIM API (OpenAI-compatible endpoint).
    Default endpoint: https://integrate.api.nvidia.com/v1/chat/completions
    User can override via config.nvidia_nim_url.

    To start a NVIDIA NIM model locally on Linux:
      docker run -d --gpus all -p 8000:8000 nvcr.io/nvidia/nim/<model-name>:latest
      export NVIDIA_NIM_API_KEY="nvapi-..."
    Then the endpoint is http://localhost:8000/v1/chat/completions
    """
    started = time.perf_counter()
    url = config.nvidia_nim_url or NVIDIA_NIM_DEFAULT_URL

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
    }
    if config.max_tokens:
        payload["max_tokens"] = config.max_tokens
    if config.min_tokens:
        payload["min_tokens"] = config.min_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=config.timeout or None)
        response.raise_for_status()
        data = response.json()

        ended = time.perf_counter()
        choice = data["choices"][0]
        content = choice["message"].get("content", "").strip()
        usage_data = data.get("usage", {})

        reasoning_details = choice["message"].get("reasoning_details")
        input_toks = usage_data.get("prompt_tokens")
        output_toks = usage_data.get("completion_tokens")
        usage = LLMUsage(
            response_time_seconds=ended - started,
            input_tokens=input_toks,
            output_tokens=output_toks,
            total_tokens=(input_toks + output_toks) if input_toks is not None and output_toks is not None else None,
        )
        return content, reasoning_details, usage
    except requests.RequestException as e:
        raise RuntimeError(f"NVIDIA NIM request failed: {e}")

ask_nvidia_nim = _with_retry(_ask_nvidia_nim_raw, max_retries=5, base_delay=3.0)


# ── Public helpers ──────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are ploxv1, a terminal-native DevOps AI assistant running inside a Linux shell environment. "
    "You can answer questions conversationally AND generate executable Linux / AWS CLI commands. "
    "When the user asks you to do something, decide whether it's a conversational question or a terminal task. "
    "For terminal tasks, respond with a JSON plan. For general questions, respond conversationally."
)


def ask_model(prompt: str, config: ModelConfig, history: list[ChatMessage], *, expect_json: bool) -> tuple:
    """Unified model call that routes to the correct backend."""
    if config.backend == "ollama":
        full_prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in _build_openai_messages(SYSTEM_PROMPT, prompt, history)
        ) if expect_json else SYSTEM_PROMPT + "\n\nOnly output valid JSON for command plans.\n\n" + prompt

        raw, reasoning, usage = ask_ollama(full_prompt, config.model_name, config)
        if expect_json:
            return _extract_json_from_text(raw), reasoning, usage
        return raw, reasoning, usage

    messages = _build_openai_messages(SYSTEM_PROMPT, prompt, history)

    if config.backend == "openrouter":
        assert config.api_key is not None, "api_key required for OpenRouter"
        raw, reasoning, usage = ask_openrouter(messages, config.model_name, config.api_key, config)
    elif config.backend == "nvidia_nim":
        assert config.api_key is not None, "api_key required for NVIDIA NIM"
        raw, reasoning, usage = ask_nvidia_nim(messages, config.model_name, config.api_key, config)
    elif config.backend == "claude":
        raw, reasoning, usage = ask_claude(messages, config.model_name, config)
    else:
        raise ValueError(f"Unknown backend: {config.backend}")

    if expect_json:
        return _extract_json_from_text(raw), reasoning, usage
    return raw, reasoning, usage


def ask_model_text(prompt: str, config: ModelConfig, history: list[ChatMessage]) -> tuple[str, object, LLMUsage]:
    """Plain-text response – used for conversational / reasoning answers."""
    return ask_model(prompt, config, history, expect_json=False)


def ask_model_json(prompt: str, config: ModelConfig, history: list[ChatMessage]) -> tuple[dict, object, LLMUsage]:
    """JSON-plan response – used for command execution plans."""
    return ask_model(prompt, config, history, expect_json=True)
