# Changelog

## Unreleased

### Safety
- **WSL runs commands in bash again.** The shell was picked by what is installed, and WSL has `powershell.exe` on its PATH, so Linux commands were sent to Windows PowerShell.
- **Only `y` / `yes` runs a plan.** Enter, a typo or any other answer used to run it.
- **The safety label comes from PloxV1's own check**, not from the model's `requires_confirmation` flag.
- **The checker looks at the whole command.** `ls && rm -rf x`, `echo x > file`, `find -delete`, `sed -i`, `curl ... | sh` and `git push -f` are now flagged.
- **Yes to ALL still asks before destructive commands**, and auto-repair stops after 3 tries.
- **Saying no to a repair stops the task.** A second "no" used to be ignored.
- **Edit keeps your edit.** It used to ask the model for a new plan and throw the edit away.
- Added tests and a GitHub Actions workflow that runs them on Linux and Windows.

### Crashes and errors
- **A rejected API key no longer crashes.** The error handler used a `config` variable it was never given.
- **Retries go by the HTTP status code.** The old check looked for the word "rate" in the error text, which is inside Ollama's URL (`api/generate`) and NVIDIA's (`integrate.api`), so a wrong key or a missing model was retried for up to 93 seconds and then reported as a rate limit.
- **Every API error is shown.** Errors other than 401, 403 and 429 used to print nothing.
- **API keys are read from the environment** (`OPENROUTER_API_KEY`, `NVIDIA_NIM_API_KEY`, `ANTHROPIC_API_KEY`) whenever none is given. `--backend openrouter` without `--api-key` used to stop on an assert, and the Claude backend ignored `--api-key` and saved keys.
- **A NIM container you run yourself needs no API key.**
- **Odd plans from the model are handled.** `"commands": "ls -la"` ran each letter as its own command, and a bare JSON list crashed.
- **`cd ~`, `cd $HOME/x` and quoted paths are followed.** They used to crash on a path that doesn't exist.
- **Ctrl+C in the middle of a task goes back to the prompt** instead of ending the session with a traceback.
- **The summary box copes with a missing token count.**
- **An empty reply or an error body from OpenRouter / NIM is reported**, not a `KeyError`.

## 2.0.0

### Security
- **Replaced `shell=True`** with safe `subprocess.run(args, shell=False)` to prevent shell injection.
- **Restricted config file permissions** to `0o600` so only the owner can read stored API keys.
- **Validate edited commands** with safety checks before accepting.
- **Removed hardcoded `/bin/bash`** — now auto-detects PowerShell on Windows, bash on Linux.

### Features
- **No timeout by default** — `timeout: Optional[int] = None` for NVIDIA NIM and other slow backends.
- **Auto-retry on 429 / server busy** with exponential backoff.
- **`[A] Yes to ALL`** — press A at any confirmation to auto-confirm all steps in the current task.
- **Cross-platform shell** — PowerShell (Windows) and bash (Linux/WSL).
- **Friendly API error messages** for 401, 403, 429 instead of raw tracebacks.

### Refactoring
- Deleted `main.py`, `context.py`, and `ai_planner.py` (dead/redundant code).
- Merged `_ask_*_raw` private functions with `_with_retry` decorator in `llm.py`.
- Centralized `_handle_api_error` in `repl.py`.
- Cleaned `prompting.py` — removed duplicate `build_repair_prompt`, kept command/chat only.
- Added `Optional` typing for `timeout` and `min_tokens`.

### UI
- **Removed purple boxes** from chat replies and command plan text (kept for config listings and help).
- **Plain text responses** for chat and command output.
- **Auto-confirm indicator** shows `[Auto-confirm: Yes to all]` when active.
- **Completion block** with random messages (CHURNED, COMPLETED, DONE, etc.) still active.
