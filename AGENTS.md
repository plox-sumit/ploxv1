# Agent Notes — PloxV1

## How to Build/Test

```bash
git clone https://github.com/plox-sumit/ploxv1.git
cd ploxv1
pip install -e ".[dev]"   # editable install with pytest and ruff

pytest               # all tests; nothing goes over the network
ruff check .         # lint

# Run it
ploxv1               # interactive setup
ploxv1 --backend ollama --model llama3
```

CI (`.github/workflows/tests.yml`) runs `ruff check` and `pytest` on Linux and Windows.

## Entry Point

`ploxv1.cli:main` is the console_scripts entry point in `pyproject.toml`.
The version lives only in `ploxv1/__init__.py`.

## Code Structure

```
ploxv1/
├── cli.py            # Argument parsing, entry point
├── llm.py            # AI backend wrappers (Ollama, OpenRouter, Claude, NVIDIA NIM), retries, LLMError
├── models.py         # Dataclasses (ModelConfig, CommandPlan, etc.)
├── repl.py           # REPL loop, UI, config storage, spinner, welcome screen
├── executor.py       # Runs one command in bash / PowerShell and streams its output
├── safety.py         # Shell choice, is_destructive() and is_read_only()
├── prompting.py      # The one prompt: the model answers with commands or with a reply
└── repair_prompting.py   # Repair prompts when commands fail
tests/                # pytest; conftest.py has a `session` fixture that scripts the REPL
```

## Key Design Decisions

- **The model picks the mode.** One prompt; the answer is `{"commands": [...]}` or `{"commands": [], "reply": "..."}`. There is no keyword guessing.
- **Safety is decided in `safety.py`, not by the model.** The model's `requires_confirmation` can only add caution. A plan is `✓ SAFE` only when every command is read-only.
- **Nothing runs without `y` / `yes`.** Any other answer cancels. `[A] Yes to ALL` lasts for one task and never covers destructive commands. Auto-repair stops after `MAX_REPAIRS`.
- **Commands run through a real shell** (`bash -c`, `powershell -Command`). That is as powerful as `shell=True`; the protection is the confirm step and `safety.py`, not the subprocess call.
- **Commands get no stdin** and their output is streamed line by line. Interactive programs fail fast instead of hanging.
- **Cross-platform shell** — picked by OS: PowerShell on Windows, bash on Linux and WSL.
- **History is sent once**, inside the prompt, with the end of each command's output.
- **Retries go by HTTP status** (408, 429, 502, 503, 504), never by the error text.
- **No timeout by default** (`timeout: Optional[int] = None`) — great for slow NVIDIA NIM.
- **API keys**: config first, then the environment (`API_KEY_ENV` in `llm.py`). Stored configs live in `~/.ploxv1_config.json`, created with `0o600` permissions (owner-only).
- **`anthropic` is an optional dependency**, imported only when the Claude backend is used.

## Coding Style

- Use `from .models import ...` for internal imports.
- Keep prompts and logic in separate files (`prompting.py`, `repair_prompting.py`).
- Use ANSI color constants from `repl.py` for consistent UI.
- Blue spinner `◜◠◝◞◟◡` during AI thinking. Green timer `⏱ 00:12`.
- Random completion messages: CHURNED, COMPLETED, DONE, etc.
- Raise `LLMError` (with the HTTP status when there is one) for backend failures.
- A bug fix comes with a test that fails without it.
- Keep the CLI/REPL prompt simple and friendly.
