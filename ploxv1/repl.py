import json
import os
import random
import re
import shutil
import sys
import threading
import time

from .models import ShellContext, ChatMessage, ModelConfig, CommandPlan, CommandExecutionResult, LLMUsage
from .llm import ask_model_text, ask_model_json, LLMError, API_KEY_ENV
from .prompting import build_prompt
from .repair_prompting import build_repair_prompt
from .executor import run_single_command
from .safety import is_destructive, is_read_only

# ── Terminal color codes ────────────────────────────────────────────
RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Purple shades (main theme)
PURP = "\033[38;5;93m"       # medium purple
PURP_L = "\033[38;5;141m"    # light purple
PURP_D = "\033[38;5;55m"     # dark purple
PURP_B = "\033[48;5;93m"     # purple background

# Accent colors
CYAN = "\033[36m"
GREEN = "\033[32m"
BRIGHT_GREEN = "\033[92m"
YELLOW = "\033[33m"
BRIGHT_YELLOW = "\033[93m"
RED = "\033[31m"
BRIGHT_RED = "\033[91m"
BLUE = "\033[34m"
BRIGHT_BLUE = "\033[94m"
WHITE = "\033[37m"
GREY = "\033[90m"

# Special
SPINNER_BLUE = "\033[38;5;39m"  # bright blue for spinner

CONFIG_PATH = os.path.expanduser("~/.ploxv1_config.json")

# ── Spinner ─────────────────────────────────────────────────────────
_spinner_running = False
_spinner_thread = None
_spinner_start = 0.0
_spinner_chars = "◜◠◝◞◟◡"


def _spin():
    idx = 0
    while _spinner_running:
        elapsed = time.perf_counter() - _spinner_start
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        timer = f"{mins:02d}:{secs:02d}"
        char = _spinner_chars[idx % len(_spinner_chars)]
        sys.stdout.write(f"\r  {SPINNER_BLUE}{char}{RST} {GREY}Thinking...{RST}  {GREEN}⏱ {timer}{RST}  ")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.12)


def spinner_start():
    global _spinner_running, _spinner_thread, _spinner_start
    _spinner_running = True
    _spinner_start = time.perf_counter()
    _spinner_thread = threading.Thread(target=_spin, daemon=True)
    _spinner_thread.start()


def spinner_stop():
    global _spinner_running, _spinner_thread
    _spinner_running = False
    if _spinner_thread:
        _spinner_thread.join(timeout=0.5)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


# ── Completion messages ─────────────────────────────────────────────
_COMPLETION_MSGS = [
    "CHURNED",
    "COMPLETED",
    "FINISHED",
    "DONE",
    "EXECUTED",
    "DELIVERED",
    "PROCESSED",
    "ACCOMPLISHED",
    "RESOLVED",
    "WRAPPED",
    "HANDLED",
    "SERVED",
    "CRUSHED",
    "NAILED",
    "LOCKED",
    "ZAPPED",
]


def print_highlight_key_val(key: str, val: str, key_color: str = PURP_L, val_color: str = WHITE):
    print(f"  {key_color}{key}:{RST} {val_color}{val}{RST}")


# ── Welcome banner ──────────────────────────────────────────────────
PLOX_LOGO = [
    "██████╗ ██╗      ██████╗ ██╗  ██╗",
    "██╔══██╗██║     ██╔═══██╗╚██╗██╔╝",
    "██████╔╝██║     ██║   ██║ ╚███╔╝ ",
    "██╔═══╝ ██║     ██║   ██║ ██╔██╗ ",
    "██║     ███████╗╚██████╔╝██╔╝ ██╗",
    "╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝",
    "",
    "██╗   ██╗  ██╗",
    "██║   ██║ ███║",
    "██║   ██║ ╚██║",
    "╚██╗ ██╔╝  ██║",
    " ╚████╔╝   ██║",
    "  ╚═══╝    ╚═╝",
]


def _write_safe(text: str):
    """Write to stdout, handling Windows encoding issues gracefully."""
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", errors="replace").decode("ascii"))


def _term_width() -> int:
    """Get terminal width, defaulting to 80 if undetectable."""
    try:
        return shutil.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


def _animate_logo(delay: float = 0.002):
    """Print the PLOX V1 logo character-by-character with a purple shimmer."""
    max_logo_width = max(len(line) for line in PLOX_LOGO)
    indent = max(0, (_term_width() - max_logo_width) // 2)

    full_logo = "\n".join(" " * indent + line for line in PLOX_LOGO)
    phase_colors = [
        "\033[38;5;55m",   # dark purple
        "\033[38;5;56m",
        "\033[38;5;57m",
        "\033[38;5;93m",   # medium purple
        "\033[38;5;129m",
        "\033[38;5;135m",
        "\033[38;5;141m",  # light purple
        "\033[38;5;147m",
        "\033[38;5;177m",
    ]

    for i, ch in enumerate(full_logo):
        color = phase_colors[i % len(phase_colors)]
        _write_safe(f"{color}{ch}{RST}")
        sys.stdout.flush()
        time.sleep(delay)
    _write_safe("\n")


def print_welcome():
    print()
    _animate_logo(delay=0.001)
    tagline1 = "Natural language → Linux & AWS CLI commands"
    tagline2 = "Chat · Explain · Reason · Execute"
    max_tagline_width = max(len(tagline1), len(tagline2))
    tag_indent = max(0, (_term_width() - max_tagline_width) // 2)
    line_pad = " " * tag_indent
    print(f"{line_pad}{DIM}{PURP}{'─' * max_tagline_width}{RST}")
    print(f"{line_pad}{DIM}{tagline1}{RST}")
    print(f"{line_pad}{DIM}{tagline2}{RST}")
    print()


# ── Config storage ──────────────────────────────────────────────────
def load_stored_configs() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_stored_configs(data: dict):
    # The file can hold API keys, so it is created owner-only rather than opened up and then locked down
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)  # for a file made by an older version
    except OSError:
        pass  # may fail on non-POSIX


def list_stored_configs():
    data = load_stored_configs()
    if not data:
        print(f"\n  {GREY}No stored configurations found.{RST}")
        return
    print(f"\n{PURP}┌{'─' * 58}┐{RST}")
    print(f"{PURP}│{RST} {BOLD}STORED CONFIGURATIONS{RST}" + " " * 34 + f"{PURP}│{RST}")
    print(f"{PURP}├{'─' * 58}┤{RST}")
    for name, cfg in data.items():
        backend = cfg.get("backend", "?")
        model = cfg.get("model_name", "?")
        max_t = cfg.get("max_tokens", "—")
        has_key = "✓" if cfg.get("api_key") else "✗"
        print(f"{PURP}│{RST} {PURP_L}{name:<20}{RST} {GREY}{backend:<12}{RST} {model:<18} max_tok:{max_t} key:{has_key} {PURP}│{RST}")
    print(f"{PURP}└{'─' * 58}┘{RST}")
    print(f"\n  {DIM}Use 'delete <name>' in setup to remove a stored config.{RST}")


def delete_stored_config(name: str) -> bool:
    data = load_stored_configs()
    if name in data:
        del data[name]
        save_stored_configs(data)
        print(f"\n  {GREEN}✓ Deleted stored config '{name}'.{RST}")
        return True
    print(f"\n  {YELLOW}⚠ Config '{name}' not found.{RST}")
    return False


def config_from_stored(cfg: dict) -> ModelConfig:
    return ModelConfig(
        backend=cfg["backend"],
        model_name=cfg["model_name"],
        api_key=cfg.get("api_key"),
        nvidia_nim_url=cfg.get("nvidia_nim_url"),
        max_tokens=cfg.get("max_tokens"),
        timeout=cfg.get("timeout", 900),
    )


# ── Model setup UI ──────────────────────────────────────────────────
def setup_model() -> ModelConfig:
    """Interactive model setup with stored config support and token limits."""
    stored = load_stored_configs()

    # Show stored configs if any
    if stored:
        list_stored_configs()
        print(f"\n  {YELLOW}Options:{RST}")
        print(f"  {BRIGHT_BLUE}[enter stored name]{RST}    → load a saved configuration")
        print(f"  {BRIGHT_BLUE}new{RST}                   → create a new configuration")
        print(f"  {BRIGHT_RED}delete <name>{RST}          → remove a stored configuration")
        print()
        choice = input(f"  {PURP_L}▶{RST} ").strip()

        if choice.lower().startswith("delete "):
            name = choice[7:].strip()
            delete_stored_config(name)
            stored = load_stored_configs()
            # Continue to let them choose or create new
            choice = "new"

        if choice.lower() != "new" and choice in stored:
            config = config_from_stored(stored[choice])
            print(f"\n  {GREEN}✓ Loaded stored config '{choice}'{RST}")
            print_highlight_key_val("Backend", config.backend)
            print_highlight_key_val("Model", config.model_name)
            print_highlight_key_val("Max Tokens", str(config.max_tokens or "model default"))
            return config

    # ── Backend selection ──
    print(f"\n{PURP}┌{'─' * 56}┐{RST}")
    print(f"{PURP}│{RST}  {BOLD}CHOOSE YOUR AI BACKEND{RST}" + " " * 29 + f"{PURP}│{RST}")
    print(f"{PURP}├{'─' * 56}┤{RST}")
    print(f"{PURP}│{RST}  {BRIGHT_BLUE}[O]{RST}  {BOLD}Ollama{RST}         — Local models (free, offline)       {PURP}│{RST}")
    print(f"{PURP}│{RST}  {BRIGHT_BLUE}[R]{RST}  {BOLD}OpenRouter{RST}     — 200+ cloud models via API           {PURP}│{RST}")
    print(f"{PURP}│{RST}  {BRIGHT_BLUE}[C]{RST}  {BOLD}Claude{RST}         — Anthropic Claude via API             {PURP}│{RST}")
    print(f"{PURP}│{RST}  {BRIGHT_BLUE}[N]{RST}  {BOLD}NVIDIA NIM{RST}     — NVIDIA NIM inference (local/cloud)   {PURP}│{RST}")
    print(f"{PURP}└{'─' * 56}┘{RST}")
    print()
    backend_choice = input(f"  {PURP_L}Your choice [O/R/C/N]:{RST} ").strip().lower()

    if backend_choice in ("o", "ollama"):
        backend = "ollama"
    elif backend_choice in ("r", "openrouter"):
        backend = "openrouter"
    elif backend_choice in ("c", "claude"):
        backend = "claude"
    elif backend_choice in ("n", "nvidia_nim", "nim", "nvidia"):
        backend = "nvidia_nim"
    else:
        print(f"\n  {YELLOW}⚠ Invalid choice, defaulting to Ollama.{RST}")
        backend = "ollama"

    # ── API key ──
    api_key = None
    nvidia_nim_url = None
    if backend in API_KEY_ENV:
        if backend == "nvidia_nim":
            print()
            print(f"{PURP}┌{'─' * 56}┐{RST}")
            print(f"{PURP}│{RST}  {BOLD}NVIDIA NIM SETUP{RST}" + " " * 35 + f"{PURP}│{RST}")
            print(f"{PURP}├{'─' * 56}┤{RST}")
            print(f"{PURP}│{RST}  To run NVIDIA NIM locally on Linux:              {PURP}│{RST}")
            print(f"{PURP}│{RST}  {DIM}$ docker run -d --gpus all -p 8000:8000 \\{RST}        {PURP}│{RST}")
            print(f"{PURP}│{RST}  {DIM}  nvcr.io/nvidia/nim/<model>:latest{RST}              {PURP}│{RST}")
            print(f"{PURP}│{RST}                                                    {PURP}│{RST}")
            print(f"{PURP}│{RST}  Then endpoint: http://localhost:8000/v1/chat/completions {PURP}│{RST}")
            print(f"{PURP}│{RST}  Or use NVIDIA cloud API (api_key required)        {PURP}│{RST}")
            print(f"{PURP}└{'─' * 56}┘{RST}")

            custom_url = input(f"\n  {PURP_L}Custom endpoint URL (ENTER for NVIDIA cloud):{RST} ").strip()
            if custom_url:
                if not custom_url.startswith(("http://", "https://")):
                    print(f"  {YELLOW}⚠ Invalid URL — must start with http:// or https://. Using NVIDIA cloud.{RST}")
                    custom_url = ""
            if custom_url:
                nvidia_nim_url = custom_url
                if not nvidia_nim_url.endswith("/chat/completions"):
                    if nvidia_nim_url.endswith("/v1"):
                        nvidia_nim_url += "/chat/completions"
                    elif not nvidia_nim_url.endswith("/v1/chat/completions"):
                        nvidia_nim_url = nvidia_nim_url.rstrip("/") + "/v1/chat/completions"

        # A key left blank is read from the environment at request time, so it is never written to the config file
        env_var = API_KEY_ENV[backend]
        api_key = input(f"  {PURP_L}API Key (or ENTER to use {env_var}):{RST} ").strip()
        if not api_key and not os.environ.get(env_var) and not nvidia_nim_url:
            print(f"  {YELLOW}⚠ No API key found. Set {env_var} before your first request.{RST}")

    # ── Model name ──
    print()
    model_name = ""
    if backend == "ollama":
        model_name = input(f"  {PURP_L}Ollama model name (e.g. llama3, codellama, mistral):{RST} ").strip() or "llama3"
    elif backend == "openrouter":
        model_name = input(f"  {PURP_L}OpenRouter model (e.g. openai/gpt-4o, anthropic/claude-sonnet-4):{RST} ").strip()
    elif backend == "claude":
        model_name = input(f"  {PURP_L}Claude model (ENTER for claude-sonnet-5-5):{RST} ").strip() or "claude-sonnet-5-5"
    elif backend == "nvidia_nim":
        model_name = input(f"  {PURP_L}NVIDIA NIM model name (e.g. meta/llama3-70b-instruct, nvidia/llama-3.1-nemotron):{RST} ").strip()

    # ── Token limits ──
    print()
    print(f"{PURP}┌{'─' * 56}┐{RST}")
    print(f"{PURP}│{RST}  {BOLD}TOKEN CONFIGURATION{RST}" + " " * 31 + f"{PURP}│{RST}")
    print(f"{PURP}├{'─' * 56}┤{RST}")
    print(f"{PURP}│{RST}  Set the maximum output tokens for this model.      {PURP}│{RST}")
    print(f"{PURP}│{RST}  Max tokens: capped at 50,000                       {PURP}│{RST}")
    print(f"{PURP}│{RST}  Leave blank to use the model's own limit           {PURP}│{RST}")
    print(f"{PURP}└{'─' * 56}┘{RST}")

    # No default cap: a number above what the model allows makes some backends reject the request
    max_tokens: int | None = None

    max_in = input(f"\n  {PURP_L}Maximum tokens (ENTER for the model's default):{RST} ").strip()
    if max_in.isdigit() and int(max_in) > 0:
        max_tokens = int(max_in)
        if max_tokens > 50000:
            print(f"  {YELLOW}⚠ Max tokens capped at 50,000. Setting to 50000.{RST}")
            max_tokens = 50000

    config = ModelConfig(
        backend=backend,
        model_name=model_name,
        api_key=api_key or None,
        nvidia_nim_url=nvidia_nim_url,
        max_tokens=max_tokens,
    )

    # ── Store config? ──
    print()
    store_choice = input(f"  {PURP_L}Store this configuration? {BRIGHT_GREEN}[Y]{RST}/{BRIGHT_RED}[N]{RST}: ").strip().lower()
    if store_choice in ("y", "yes", ""):
        cfg_name = input(f"  {PURP_L}Give this config a name (e.g. 'home-server', 'work'):{RST} ").strip() or f"{backend}-{model_name}"
        stored[cfg_name] = {
            "backend": backend,
            "model_name": model_name,
            "api_key": api_key or None,
            "nvidia_nim_url": nvidia_nim_url,
            "max_tokens": max_tokens,
        }
        save_stored_configs(stored)
        print(f"\n  {GREEN}✓ Saved as '{cfg_name}'{RST}")

    return config


# ── Print completion block ──────────────────────────────────────────
def print_completion_block(usage: LLMUsage):
    msg = random.choice(_COMPLETION_MSGS)
    elapsed = usage.response_time_seconds
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print()
    print(f"{PURP}┌{'─' * 50}┐{RST}")
    print(f"{PURP}│{RST}  {BOLD}{BRIGHT_GREEN}{msg}{RST}" + " " * (48 - len(msg)) + f"{PURP}│{RST}")
    print(f"{PURP}├{'─' * 50}┤{RST}")
    print(f"{PURP}│{RST}  {PURP_L}⏱ Time:{RST}  {WHITE}{mins}m {secs}s{RST}" + " " * (34 - len(f"{mins}m {secs}s")) + f"{PURP}│{RST}")
    if usage.total_tokens:
        # A backend can report one count without the other
        tokens_in = "?" if usage.input_tokens is None else f"{usage.input_tokens:,}"
        tokens_out = "?" if usage.output_tokens is None else f"{usage.output_tokens:,}"
        print(f"{PURP}│{RST}  {PURP_L}🔢 Tokens:{RST} {WHITE}{usage.total_tokens:,}{RST} (in: {tokens_in} | out: {tokens_out})" + " " * 5 + f"{PURP}│{RST}")
    print(f"{PURP}└{'─' * 50}┘{RST}")
    print()


def _handle_api_error(error: LLMError, config: ModelConfig):
    """Print a user-friendly message for an API error."""
    if error.status == 401:
        print(f"\n  {BRIGHT_RED}✗ Authentication failed.{RST}")
        print(f"  {YELLOW}Your API key was rejected. Please check:{RST}")
        print(f"    1. Did you select the correct backend? (You chose: {config.backend})")
        if config.backend == "nvidia_nim":
            print("    2. NVIDIA NIM needs an NVIDIA API key (nvapi-...). Set NVIDIA_NIM_API_KEY env var.")
            print("    3. Or use a local NIM docker container instead of the cloud API.")
        elif config.backend == "openrouter":
            print("    2. OpenRouter needs an OpenRouter API key (sk-or-...). Set OPENROUTER_API_KEY env var.")
        elif config.backend == "claude":
            print("    2. Claude needs an Anthropic API key (sk-ant-...). Set ANTHROPIC_API_KEY env var.")
        print(f"\n  {CYAN}Run again and enter a valid API key when prompted.{RST}")
    elif error.status == 403:
        print(f"\n  {BRIGHT_RED}✗ Access forbidden.{RST} Check that your API key has the correct permissions.")
    elif error.status == 429:
        print(f"\n  {BRIGHT_YELLOW}⚠ Rate limited. Too many requests. Wait a minute and try again.{RST}")
    else:
        print(f"\n  {BRIGHT_RED}✗ {error}{RST}")


MAX_REPAIRS = 3


# How much of each command's output is kept in the history the model sees
HISTORY_OUTPUT_CHARS = 500


def _with_spinner(ask, prompt: str, config: ModelConfig) -> tuple:
    spinner_start()
    try:
        return ask(prompt, config)
    finally:
        spinner_stop()


def _say(reply: str):
    # No purple box for chat replies - just plain text
    print()
    print(f"  {BOLD}{PURP_L}🦊 ploxv1 says:{RST}")
    print(f"  {reply}")


def _commands(answer: dict) -> list[str]:
    """The plan's commands as a clean list. Small models don't always send a list of strings."""
    commands = answer.get("commands", [])
    if isinstance(commands, str):
        commands = [commands]
    if not isinstance(commands, list):
        return []
    return [c.strip() for c in commands if isinstance(c, str) and c.strip()]


def _read_answer(answer: dict) -> CommandPlan | str | None:
    """Turn the model's JSON into a plan to run or a reply to show. None when it is neither."""
    if "error" in answer:
        # Not JSON. A mangled plan is unusable; anything else is the model answering in plain text.
        raw = answer["raw"].strip()
        return None if '"commands"' in raw else (raw or None)

    commands = _commands(answer)
    if commands:
        return CommandPlan(
            summary=str(answer.get("summary") or "No summary"),
            commands=commands,
            requires_confirmation=bool(answer.get("requires_confirmation", True)),
        )

    reply = answer.get("reply")
    return reply.strip() if isinstance(reply, str) and reply.strip() else None


def _ask_model(prompt: str, config: ModelConfig, *, is_repair: bool) -> tuple[CommandPlan | str | None, LLMUsage | None]:
    """Ask the model what to do. Returns a plan to run or a reply to show,
    or None (with the reason already printed) when it gave neither."""
    try:
        answer, _, usage = _with_spinner(ask_model_json, prompt, config)
        result = _read_answer(answer)

        if result is None and not is_repair:
            said = answer["raw"] if "error" in answer else json.dumps(answer)
            retry_prompt = (
                prompt
                + f"\n\n!!! YOUR LAST ANSWER COULD NOT BE USED. You said:\n{said[:300]}\n\n"
                + "NOW OUTPUT ONLY THE JSON OBJECT: either commands or a reply. No markdown. No backticks."
            )
            answer, _, usage = _with_spinner(ask_model_json, retry_prompt, config)
            result = _read_answer(answer)
    except LLMError as e:
        _handle_api_error(e, config)
        return None, None

    if result is None:
        print(f"\n  {BOLD}{YELLOW}⚠ The model gave no commands and no answer.{RST}")
        print_completion_block(usage)
    return result, usage


def _transcript(results: list[CommandExecutionResult]) -> str:
    """What ran and the end of what it printed, so the model can answer questions about it."""
    return "\n".join(f"$ {r.command}\n{r.output.strip()[-HISTORY_OUTPUT_CHARS:]}".rstrip() for r in results)


def _show_plan(plan: CommandPlan):
    # The label comes from our own check of the commands. The model can ask for
    # confirmation, but it can't mark its own commands as safe.
    if any(is_destructive(c) for c in plan.commands):
        label_color, label = BRIGHT_RED, "⚠ DESTRUCTIVE — this can delete or overwrite things"
    elif plan.requires_confirmation or not all(is_read_only(c) for c in plan.commands):
        label_color, label = BRIGHT_YELLOW, "⚠ NEEDS CONFIRMATION"
    else:
        label_color, label = BRIGHT_GREEN, "✓ SAFE"

    print()
    print(f"  {BOLD}{PURP_L}📋 PLAN: {plan.summary}{RST}")
    print()
    print(f"  {CYAN}Commands to run:{RST}")
    for c in plan.commands:
        if is_destructive(c):
            print(f"    {BRIGHT_RED}$ {c}  ⚠{RST}")
        else:
            print(f"    {BRIGHT_BLUE}$ {c}{RST}")

    print(f"\n  {label_color}{label}{RST}")


def _confirm_plan(plan: CommandPlan, auto_confirm: bool) -> tuple[str, bool]:
    """Show the plan and ask what to do with it.
    Returns ('run' | 'cancel' | 'chat', auto_confirm)."""
    while True:
        _show_plan(plan)

        destructive = any(is_destructive(c) for c in plan.commands)
        if auto_confirm and not destructive:
            print(f"  {DIM}[Auto-confirm: Yes to all]{RST}")
            return "run", auto_confirm
        if auto_confirm:
            print(f"  {DIM}[Auto-confirm does not cover destructive commands]{RST}")

        print(f"  {BRIGHT_GREEN}[Y]{RST} = Run it  {BRIGHT_RED}[N]{RST} = Cancel  {YELLOW}[E]{RST} = Edit  {PURP_L}[C]{RST} = Chat  {BRIGHT_GREEN}[A]{RST} = Yes to ALL this task")
        decision = input(f"  {PURP_L}▶{RST} ").strip().lower()

        if decision in ("y", "yes"):
            return "run", auto_confirm
        if decision == "a":
            print(f"  {GREEN}✓ Auto-confirm enabled for this task. Only destructive steps will ask again.{RST}")
            return "run", True
        if decision == "c":
            return "chat", auto_confirm
        if decision == "e":
            print(f"\n  {PURP_L}Commands to edit:{RST}")
            for i, c in enumerate(plan.commands):
                print(f"  {BRIGHT_BLUE}[{i}]{RST} {c}")
            idx = input(f"  {PURP_L}Which command number to edit?{RST} ").strip()
            if idx.isdigit() and int(idx) < len(plan.commands):
                new_cmd = input(f"  {PURP_L}New command:{RST} ").strip()
                if new_cmd:
                    plan.commands[int(idx)] = new_cmd
                    print(f"  {GREEN}✓ Updated.{RST}")
            # Show the plan again, with the safety label worked out for the edited command
            continue
        # Anything that is not a clear yes is a no
        return "cancel", auto_confirm


def _run_plan(plan: CommandPlan, context: ShellContext) -> list[CommandExecutionResult]:
    """Run the commands in order, stopping at the first one that fails. Returns what ran."""
    print(f"\n  {SPINNER_BLUE}⚡ Executing...{RST}")
    results = []
    for i, cmd in enumerate(plan.commands):
        print(f"  {BRIGHT_BLUE}[{i+1}/{len(plan.commands)}]{RST} $ {cmd}")
        # Output is printed line by line as the command runs
        result = run_single_command(cmd, on_line=lambda line: print(f"  {DIM}  | {line}{RST}"))
        results.append(result)

        if result.returncode != 0:
            print(f"  {BRIGHT_RED}  ✗ FAILED (code {result.returncode}){RST}")
            break

        if not result.output.strip():
            print(f"  {GREEN}  ✓ OK{RST}")

        # A lone `cd` only moved the child shell, so move ploxv1 itself there too.
        # `cd x && ls` is left alone: there the move is meant to last for that one line.
        lone_cd = re.fullmatch(r"cd\s+([^;&|<>]+)", cmd.strip())
        if lone_cd:
            target = os.path.expandvars(os.path.expanduser(lone_cd.group(1).strip().strip("'\"")))
            try:
                os.chdir(os.path.join(context.cwd, target))
                context.cwd = os.getcwd()
            except OSError as e:
                print(f"  {YELLOW}  ⚠ Could not follow cd: {e}{RST}")
    return results


def _handle_request(user_inp: str, config: ModelConfig, context: ShellContext, history: list[ChatMessage]):
    """Answer one request: a chat reply, or a plan that is confirmed, run and repaired."""
    # The model decides whether this is a question to answer or a task to run
    prompt = build_prompt(user_inp, context, history)
    history.append(ChatMessage(role="user", content=user_inp))
    repairs = 0
    # Auto-confirm lasts for one task
    auto_confirm = False

    while True:
        plan, usage = _ask_model(prompt, config, is_repair=repairs > 0)
        if plan is None:
            break

        if isinstance(plan, str):
            _say(plan)
            history.append(ChatMessage(role="assistant", content=plan))
            print_completion_block(usage)
            break

        decision, auto_confirm = _confirm_plan(plan, auto_confirm)

        if decision == "cancel":
            print(f"  {YELLOW}✗ Cancelled.{RST}")
            history.append(ChatMessage(role="assistant", content=f"[Plan was shown but user cancelled]: {plan.summary}"))
            print_completion_block(usage)
            break

        if decision == "chat":
            # Switch to chat mode - NO PURPLE BOX for chat
            chat_prompt = f"The user saw this plan and wants to chat instead:\n\nPlan: {plan.summary}\nCommands: {', '.join(plan.commands)}\n\nUser said: {user_inp}\n\nHave a conversation about this. Explain what the commands do, suggest alternatives, answer questions."
            try:
                reply, _, chat_usage = _with_spinner(ask_model_text, chat_prompt, config)
            except LLMError as e:
                _handle_api_error(e, config)
                break
            _say(reply)
            history.append(ChatMessage(role="assistant", content=reply))
            print_completion_block(chat_usage)
            break

        results = _run_plan(plan, context)

        if results[-1].returncode == 0:
            history.append(ChatMessage(role="assistant", content=f"[Ran: {plan.summary}]\n{_transcript(results)}"))
            print_completion_block(usage)
            break

        # Offer repair
        if repairs >= MAX_REPAIRS:
            print(f"  {YELLOW}✗ Still failing after {MAX_REPAIRS} repair attempts. Stopping.{RST}")
            repair_choice = "n"
        elif not auto_confirm:
            print()
            repair_choice = input(f"  {YELLOW}Try to auto-repair? {BRIGHT_GREEN}[Y]{RST}/{BRIGHT_RED}[N]{RST}:{RST} ").strip().lower()
        else:
            print(f"  {GREEN}  [Auto-repairing...]{RST}")
            repair_choice = "y"

        if repair_choice not in ("y", "yes", ""):
            print(f"  {YELLOW}✗ Abandoned.{RST}")
            history.append(ChatMessage(role="assistant", content=f"[Failed and abandoned: {plan.summary}]\n{_transcript(results)}"))
            break

        repairs += 1
        prompt = build_repair_prompt(user_inp, plan, results[-1], context)
    # End of while True (command loop)

    if auto_confirm:
        print(f"  {GREY}[Auto-confirm disabled — new task will ask again]{RST}")


def repl_loop(config: ModelConfig):
    context = ShellContext(
        cwd=os.getcwd(),
        os_name="windows" if os.name == "nt" else "linux",
        aws_profile=os.environ.get("AWS_PROFILE"),
        aws_region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    )
    history: list[ChatMessage] = []

    print_highlight_key_val("Backend", config.backend, PURP_L, WHITE)
    print_highlight_key_val("Model", config.model_name, PURP_L, WHITE)
    print_highlight_key_val("Max Tokens", str(config.max_tokens or "model default"), PURP_L, WHITE)
    print()
    print(f"  {DIM}Type /help for commands, /exit to quit, /clear to reset history{RST}")
    print(f"  {DIM}You can chat naturally OR ask me to do terminal tasks!{RST}")
    print()

    while True:
        try:
            user_inp = input(f"{PURP_L}🦊 {BOLD}You:{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {PURP_L}👋 Goodbye!{RST}\n")
            break

        if not user_inp:
            continue

        # ── Slash commands ──
        if user_inp.startswith("/"):
            cmd = user_inp[1:].strip().lower()
            if cmd in ("exit", "quit", "q"):
                print(f"\n  {PURP_L}👋 Goodbye!{RST}\n")
                break
            elif cmd == "help":
                print(f"""
{PURP}┌{'─' * 50}┐{RST}
{PURP}│{RST}  {BOLD}COMMANDS{RST}                                        {PURP}│{RST}
{PURP}├{'─' * 50}┤{RST}
{PURP}│{RST}  /help     — Show this help                       {PURP}│{RST}
{PURP}│{RST}  /exit     — Quit ploxv1                           {PURP}│{RST}
{PURP}│{RST}  /clear    — Clear conversation history            {PURP}│{RST}
{PURP}│{RST}  /config   — Show current config                   {PURP}│{RST}
{PURP}│{RST}  /stored   — List all stored configurations        {PURP}│{RST}
{PURP}│{RST}  /switch   — Switch to a stored config             {PURP}│{RST}
{PURP}└{'─' * 50}┘{RST}
""")
                continue
            elif cmd == "clear":
                history = []
                print(f"  {GREEN}✓ History cleared.{RST}")
                continue
            elif cmd == "config":
                print_highlight_key_val("Backend", config.backend)
                print_highlight_key_val("Model", config.model_name)
                print_highlight_key_val("Max Tokens", str(config.max_tokens or "model default"))
                if config.nvidia_nim_url:
                    print_highlight_key_val("NIM URL", config.nvidia_nim_url)
                continue
            elif cmd == "stored":
                list_stored_configs()
                continue
            elif cmd == "switch":
                stored = load_stored_configs()
                if not stored:
                    print(f"\n  {YELLOW}No stored configs. Create one first.{RST}")
                    continue
                list_stored_configs()
                name = input(f"\n  {PURP_L}Config name to switch to:{RST} ").strip()
                if name in stored:
                    config = config_from_stored(stored[name])
                    history = []
                    print(f"\n  {GREEN}✓ Switched to '{name}'. History cleared.{RST}")
                else:
                    print(f"\n  {YELLOW}⚠ Config '{name}' not found.{RST}")
                continue
            else:
                print(f"  {YELLOW}Unknown command. Type /help for available commands.{RST}")
                continue

        try:
            _handle_request(user_inp, config, context, history)
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C or Ctrl+D in the middle of a task drops the task, not the session
            print(f"\n  {YELLOW}✗ Interrupted.{RST}")
