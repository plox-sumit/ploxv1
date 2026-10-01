import functools
import json
import os
import time
import requests
from .models import ModelConfig, LLMUsage

OLLAMA_URL = "http://localhost:11434/api/generate"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NVIDIA_NIM_DEFAULT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Keep answers as steady as the backend allows. At the backends' own defaults
# (0.7 to 1.0) a small model sometimes chatted when asked for a command, and the other way round.
TEMPERATURE = 0

API_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


class LLMError(RuntimeError):
    """A backend call failed. `status` is the HTTP status, or None when there was no response."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _request_error(backend: str, e: requests.RequestException) -> LLMError:
    # A timeout has no response, so give it the HTTP code that means the same thing.
    status = 408 if isinstance(e, requests.Timeout) else getattr(e.response, "status_code", None)
    return LLMError(f"{backend} request failed: {e}", status)


def _api_key(config: ModelConfig, *, required: bool = True) -> str | None:
    env_var = API_KEY_ENV[config.backend]
    key = config.api_key or os.environ.get(env_var)
    if required and not key:
        raise LLMError(f"No API key for {config.backend}. Set {env_var} or pass --api-key.")
    return key


# ── Retry decorator for transient API failures ──────────────────────
# Timeout, rate limit, bad gateway, unavailable, gateway timeout
RETRY_STATUSES = {408, 429, 502, 503, 504}


def _with_retry(func, *, max_retries=3, base_delay=2.0):
    """Decorator: retry on 429 and certain transient errors with exponential backoff."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except LLMError as e:
                # Go by the status code. The error text holds the URL, and
                # "api/generate" and "integrate.api" both contain "rate".
                if e.status not in RETRY_STATUSES or attempt == max_retries:
                    raise
                delay = base_delay * (2 ** attempt)
                retry_note = f"Retrying in {delay:.0f}s... ({attempt+1}/{max_retries})"
                print(f"  [Rate limited / server busy. {retry_note}]", flush=True)
                time.sleep(delay)
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

    # Try direct parse first. A bare list or string is valid JSON but not a plan.
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
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


def _build_openai_messages(system_prompt: str, user_content: str) -> list[dict]:
    # The prompt already carries the recent history, so it is sent once, as one user message.
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _first_message(backend: str, data: dict) -> dict:
    # Some providers answer 200 with an error body instead of choices.
    if not data.get("choices"):
        raise LLMError(f"{backend} returned no answer: {str(data.get('error', data))[:300]}")
    return data["choices"][0]["message"]


# ── Ollama ──────────────────────────────────────────────────────────
def _ask_ollama_raw(prompt: str, model: str, config: ModelConfig, json_mode: bool) -> tuple[str, object, LLMUsage]:
    started = time.perf_counter()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    payload["options"] = {"temperature": TEMPERATURE}
    if json_mode:
        # Ollama then only lets the model produce valid JSON
        payload["format"] = "json"
    if config.max_tokens:
        payload["options"]["num_predict"] = config.max_tokens

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
    except requests.ConnectionError:
        raise LLMError("Can't reach Ollama at http://localhost:11434. Is it running? Start it with: ollama serve")
    except requests.RequestException as e:
        raise _request_error("Ollama", e)

ask_ollama = _with_retry(_ask_ollama_raw, max_retries=3, base_delay=1.0)


# ── OpenRouter ──────────────────────────────────────────────────────
def _ask_openrouter_raw(messages: list[dict], model: str, api_key: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": TEMPERATURE,
    }
    if config.max_tokens:
        payload["max_tokens"] = config.max_tokens

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
        message = _first_message("OpenRouter", data)
        content = (message.get("content") or "").strip()
        usage_data = data.get("usage", {})

        reasoning_details = message.get("reasoning_details")
        usage = LLMUsage(
            response_time_seconds=ended - started,
            input_tokens=usage_data.get("prompt_tokens"),
            output_tokens=usage_data.get("completion_tokens"),
            total_tokens=usage_data.get("total_tokens"),
        )
        return content, reasoning_details, usage
    except requests.RequestException as e:
        raise _request_error("OpenRouter", e)

ask_openrouter = _with_retry(_ask_openrouter_raw, max_retries=3, base_delay=2.0)


# ── Anthropic Claude ────────────────────────────────────────────────
def _ask_claude_raw(messages: list[dict], model: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    api_key = _api_key(config)
    # Imported here so the other backends work without the anthropic package installed
    try:
        import anthropic
    except ImportError:
        raise LLMError(
            "The Claude backend needs the anthropic package. "
            "Install it with: pip install anthropic   (with pipx: pipx inject ploxv1 anthropic)"
        )

    started = time.perf_counter()
    client = anthropic.Anthropic(api_key=api_key, timeout=config.timeout or 600, max_retries=2)

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
    # Claude needs a limit. 4096 fits every Claude model and is far more than a plan or a short answer uses.
    kwargs["max_tokens"] = config.max_tokens or 4096

    try:
        resp = client.messages.create(**kwargs)

        ended = time.perf_counter()
        content = "".join(block.text for block in resp.content if block.type == "text")
        reasoning_details = None

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
        raise LLMError(f"Anthropic request failed: {e}", getattr(e, "status_code", None))

ask_claude = _with_retry(_ask_claude_raw, max_retries=3, base_delay=2.0)


# ── NVIDIA NIM ──────────────────────────────────────────────────────
def _ask_nvidia_nim_raw(messages: list[dict], model: str, api_key: str | None, config: ModelConfig) -> tuple[str, object, LLMUsage]:
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
        "temperature": TEMPERATURE,
    }
    if config.max_tokens:
        payload["max_tokens"] = config.max_tokens

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=config.timeout or None)
        response.raise_for_status()
        data = response.json()

        ended = time.perf_counter()
        message = _first_message("NVIDIA NIM", data)
        content = (message.get("content") or "").strip()
        usage_data = data.get("usage", {})

        reasoning_details = message.get("reasoning_details")
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
        raise _request_error("NVIDIA NIM", e)

ask_nvidia_nim = _with_retry(_ask_nvidia_nim_raw, max_retries=5, base_delay=3.0)


# ── Public helpers ──────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are ploxv1, a terminal assistant for Linux and AWS CLI work. "
    "Follow the instructions in the user message exactly."
)


def ask_model(prompt: str, config: ModelConfig, *, expect_json: bool) -> tuple:
    """Unified model call that routes to the correct backend."""
    if config.backend == "ollama":
        full_prompt = SYSTEM_PROMPT + "\n\n" + prompt
        raw, reasoning, usage = ask_ollama(full_prompt, config.model_name, config, expect_json)
        if expect_json:
            return _extract_json_from_text(raw), reasoning, usage
        return raw, reasoning, usage

    messages = _build_openai_messages(SYSTEM_PROMPT, prompt)

    if config.backend == "openrouter":
        raw, reasoning, usage = ask_openrouter(messages, config.model_name, _api_key(config), config)
    elif config.backend == "nvidia_nim":
        # A NIM container you run yourself needs no key; NVIDIA's cloud does.
        api_key = _api_key(config, required=not config.nvidia_nim_url)
        raw, reasoning, usage = ask_nvidia_nim(messages, config.model_name, api_key, config)
    elif config.backend == "claude":
        raw, reasoning, usage = ask_claude(messages, config.model_name, config)
    else:
        raise ValueError(f"Unknown backend: {config.backend}")

    if expect_json:
        return _extract_json_from_text(raw), reasoning, usage
    return raw, reasoning, usage


def ask_model_text(prompt: str, config: ModelConfig) -> tuple[str, object, LLMUsage]:
    """Plain-text response – used when chatting about a plan."""
    return ask_model(prompt, config, expect_json=False)


def ask_model_json(prompt: str, config: ModelConfig) -> tuple[dict, object, LLMUsage]:
    """JSON response – a command plan or a reply."""
    return ask_model(prompt, config, expect_json=True)
