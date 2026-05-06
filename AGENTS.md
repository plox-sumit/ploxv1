# Agent Notes — PloxV1

## How to Build/Test

```bash
cd ~/ploxv1          # or wherever the repo lives
pip install -e .     # editable install for development

# Run it
ploxv1               # interactive setup
ploxv1 --backend ollama --model llama3
```

## Entry Point

`ploxv1.cli:main` is the console_scripts entry point in `pyproject.toml`.

## Code Structure

```
ploxv1/
├── cli.py            # Argument parsing, entry point
├── llm.py            # AI backend wrappers (Ollama, OpenRouter, Claude, NVIDIA NIM)
├── models.py         # Dataclasses (ModelConfig, CommandPlan, etc.)
├── repl.py           # REPL loop, UI, config storage, spinner, welcome screen
├── executor.py       # Safe shell command runner (subprocess, shell=False)
├── safety.py         # Command safety classification (destructive vs harmless)
├── prompting.py      # Prompt construction for command/chat modes
└── repair_prompting.py   # Repair prompts when commands fail
```

## Key Design Decisions

- **No timeout by default** (`timeout: Optional[int] = None`) — great for slow NVIDIA NIM.
- **Auto-retry on 429** — exponential backoff, backend-specific retry counts.
- **Cross-platform shell** — PowerShell on Windows, bash on Linux.
- **`[A] Yes to ALL`** — per-task-session auto-confirm.
- **API keys stored in `~/.ploxv1_config.json`** with `0o600` permissions (owner-only).
- **Deletes** (old, not removed): `main.py`, `context.py`, `ai_planner.py`.

## Coding Style

- Use `from .models import ...` for internal imports.
- Keep prompts and logic in separate files (`prompting.py`, `repair_prompting.py`).
- Use ANSI color constants from `repl.py` for consistent UI.
- Blue spinner `◜◠◝◞◟◡` during AI thinking. Green timer `⏱ 00:12`.
- Random completion messages: CHURNED, COMPLETED, DONE, etc.
- NEVER use `shell=True` in `subprocess.run()`.
- Keep the CLI/REPL prompt simple and friendly.
