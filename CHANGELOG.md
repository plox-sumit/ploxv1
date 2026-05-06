# Changelog


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
