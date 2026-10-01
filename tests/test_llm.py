import sys

import pytest
import requests

from ploxv1 import llm
from ploxv1.llm import LLMError
from ploxv1.models import ModelConfig


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: http://x/api/generate", response=self)

    def json(self):
        return self._data


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    return waits


def failing(calls, status, text="request failed"):
    def func():
        calls.append(1)
        raise LLMError(text, status)

    return func


# The URLs of Ollama ("api/generate") and NVIDIA ("integrate.api") both contain "rate".
@pytest.mark.parametrize("status, text", [
    (404, "Ollama request failed: 404 Not Found for url: http://localhost:11434/api/generate"),
    (401, "NVIDIA NIM request failed: 401 Unauthorized for url: https://integrate.api.nvidia.com/v1/chat/completions"),
    (None, "No API key"),
])
def test_errors_that_will_not_fix_themselves_are_not_retried(no_sleep, capsys, status, text):
    calls = []
    with pytest.raises(LLMError):
        llm._with_retry(failing(calls, status, text), max_retries=3)()
    assert len(calls) == 1
    assert no_sleep == []


@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
def test_busy_server_is_retried(no_sleep, capsys, status):
    calls = []
    with pytest.raises(LLMError):
        llm._with_retry(failing(calls, status), max_retries=3, base_delay=1.0)()
    assert len(calls) == 4
    assert no_sleep == [1.0, 2.0, 4.0]


def test_request_errors_carry_their_status():
    http_error = requests.HTTPError("401 Unauthorized", response=FakeResponse(401))
    assert llm._request_error("OpenRouter", http_error).status == 401
    assert llm._request_error("OpenRouter", requests.Timeout("slow")).status == 408
    assert llm._request_error("OpenRouter", requests.ConnectionError("down")).status is None


def test_api_key_comes_from_the_config_then_the_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert llm._api_key(ModelConfig(backend="openrouter", model_name="m", api_key="from-config")) == "from-config"
    assert llm._api_key(ModelConfig(backend="openrouter", model_name="m")) == "from-env"


@pytest.mark.parametrize("backend", ["openrouter", "nvidia_nim", "claude"])
def test_missing_api_key_is_a_clear_error(monkeypatch, backend):
    monkeypatch.delenv(llm.API_KEY_ENV[backend], raising=False)
    with pytest.raises(LLMError, match=llm.API_KEY_ENV[backend]):
        llm.ask_model_text("hi", ModelConfig(backend=backend, model_name="m"))


def test_a_local_nim_container_needs_no_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers)
        return FakeResponse(data={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    config = ModelConfig(backend="nvidia_nim", model_name="m", nvidia_nim_url="http://localhost:8000/v1/chat/completions")
    reply, _, _ = llm.ask_model_text("hi", config)
    assert reply == "hi"
    assert "Authorization" not in sent["headers"]


def openrouter_answer(monkeypatch, data):
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: FakeResponse(data=data))
    config = ModelConfig(backend="openrouter", model_name="m", api_key="k")
    return llm.ask_model_text("hi", config)


def test_empty_content_is_an_empty_reply(monkeypatch):
    reply, _, _ = openrouter_answer(monkeypatch, {"choices": [{"message": {"content": None}}]})
    assert reply == ""


def test_error_body_with_status_200_is_reported(monkeypatch):
    with pytest.raises(LLMError, match="model not found"):
        openrouter_answer(monkeypatch, {"error": {"message": "model not found"}})


def test_ollama_that_is_not_running_says_so(monkeypatch, no_sleep):
    def refuse(*args, **kwargs):
        raise requests.ConnectionError("Max retries exceeded with url: /api/generate")

    monkeypatch.setattr(llm.requests, "post", refuse)
    with pytest.raises(LLMError, match="ollama serve"):
        llm.ask_model_text("hi", ModelConfig(backend="ollama", model_name="m"))
    assert no_sleep == []


@pytest.mark.parametrize("raw", ['["ls -la"]', '"ls -la"', "null", "42"])
def test_json_that_is_not_an_object_is_a_parse_error(raw):
    assert "error" in llm._extract_json_from_text(raw)


def test_plan_wrapped_in_a_list_is_unwrapped():
    assert llm._extract_json_from_text('[{"commands": ["ls"]}]') == {"commands": ["ls"]}


# ── What is sent to the backends ──


def sent_to(monkeypatch, backend, ask, **config):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(json)
        return FakeResponse(data={"response": "{}", "choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    ask("THE PROMPT", ModelConfig(backend=backend, model_name="m", api_key="k", **config))
    return sent


def test_chat_backends_get_one_system_and_one_user_message(monkeypatch):
    sent = sent_to(monkeypatch, "openrouter", llm.ask_model_json)
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert sent["messages"][1]["content"] == "THE PROMPT"


def test_ollama_json_mode_is_on_for_plans_only(monkeypatch):
    assert sent_to(monkeypatch, "ollama", llm.ask_model_json)["format"] == "json"
    text = sent_to(monkeypatch, "ollama", llm.ask_model_text)
    assert "format" not in text
    assert "Only output valid JSON" not in text["prompt"]
    assert text["prompt"].count(llm.SYSTEM_PROMPT) == 1


@pytest.mark.parametrize("backend", ["openrouter", "nvidia_nim"])
def test_no_token_limits_are_sent_unless_asked_for(monkeypatch, backend):
    sent = sent_to(monkeypatch, backend, llm.ask_model_json)
    assert "max_tokens" not in sent
    assert "min_tokens" not in sent
    assert sent_to(monkeypatch, backend, llm.ask_model_json, max_tokens=800)["max_tokens"] == 800


@pytest.mark.parametrize("backend", ["ollama", "openrouter", "nvidia_nim"])
def test_temperature_is_pinned(monkeypatch, backend):
    sent = sent_to(monkeypatch, backend, llm.ask_model_json)
    assert (sent.get("options") or sent)["temperature"] == 0


def test_claude_without_the_anthropic_package_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` fail
    with pytest.raises(LLMError, match="pip install anthropic"):
        llm.ask_model_text("hi", ModelConfig(backend="claude", model_name="m", api_key="k"))
