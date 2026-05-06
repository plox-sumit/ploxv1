import json
import os
import random
import shutil
import sys
import threading
import time

from .models import ShellContext, ChatMessage, ModelConfig, CommandPlan, CommandExecutionResult, LLMUsage
from .llm import ask_model_text, ask_model_json
from .prompting import build_command_prompt, build_chat_prompt
from .repair_prompting import build_repair_prompt
from .executor import run_single_command
from .safety import is_destructive

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


# ── Box drawing helpers ─────────────────────────────────────────────
def box(text: str, border_color: str = PURP, width: int = 70) -> str:
    lines = text.strip().split("\n")
    top = f"{border_color}╭{'─' * (width - 2)}╮{RST}"
    mid = []
    for line in lines:
        visible_len = len(line.replace("\033", ""))  # approximate
        padded = line + " " * max(0, width - 2 - _visible_len(line))
        mid.append(f"{border_color}│{RST} {padded}{border_color}│{RST}")
    bot = f"{border_color}╰{'─' * (width - 2)}╯{RST}"
    return "\n".join([top] + mid + [bot])


def _visible_len(s: str) -> int:
    """Approximate visible length of a string with ANSI codes."""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def colored_box(text: str, border_color: str = PURP, fill_color: str = "", width: int = 68) -> str:
    """Draw a box with optional background fill color."""
    lines = text.strip().split("\n")
    top = f"{border_color}╭{'─' * (width - 2)}╮{RST}"
    mid = []
    for line in lines:
        vl = _visible_len(line)
        padded = line + " " * max(0, width - 2 - vl)
        if fill_color:
            mid.append(f"{border_color}│{fill_color}{padded}{RST}{border_color}│{RST}")
        else:
            mid.append(f"{border_color}│{RST} {padded}{border_color}│{RST}")
    bot = f"{border_color}╰{'─' * (width - 2)}╯{RST}"
    return "\n".join([top] + mid + [bot])


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

PLOX_COLORS = [PURP_D, PURP, PURP_L, "\033[38;5;135m", "\033[38;5;171m", "\033[38;5;177m"]


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
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_stored_configs(data: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
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
            cfg_data = stored[choice]
            config = ModelConfig(
                backend=cfg_data["backend"],
                model_name=cfg_data["model_name"],
                api_key=cfg_data.get("api_key"),
                nvidia_nim_url=cfg_data.get("nvidia_nim_url"),
                max_tokens=cfg_data.get("max_tokens"),
                min_tokens=cfg_data.get("min_tokens"),
                timeout=cfg_data.get("timeout", 900),
            )
            print(f"\n  {GREEN}✓ Loaded stored config '{choice}'{RST}")
            print_highlight_key_val("Backend", config.backend)
            print_highlight_key_val("Model", config.model_name)
            print_highlight_key_val("Max Tokens", str(config.max_tokens or "50000"))
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
    if backend in ("openrouter", "nvidia_nim"):
        if backend == "nvidia_nim":
            print()
            print(f"{PURP}┌{'─' * 56}┐{RST}")
            print(f"{PURP}│{RST}  {BOLD}NVIDIA NIM SETUP{RST}" + " " * 35 + f"{PURP}│{RST}")
            print(f"{PURP}├{'─' * 56}┤{RST}")
            print(f"{PURP}│{RST}  To run NVIDIA NIM locally on Linux:              {PURP}│{RST}")
            print(f"{PURP}│{RST}  {DIM}$ docker run -d --gpus all -p 8000:8000 \\{RST}        {PURP}│{RST}")
            print(f"{PURP}│{RST}  {DIM}  nvcr.io/nvidia/nim/<model>:latest{RST}              {PURP}│{RST}")
            print(f"{PURP}│{RST}                                                    {PURP}│{RST}")
            print(f"{PURP}│{RST}  Then endpoint: http://localhost:8000/v1/chat/completions {PURP}│{RST}│{RST}")
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

        api_key = input(f"  {PURP_L}API Key (or ENTER to use env var):{RST} ").strip()
        if not api_key:
            env_var = "OPENROUTER_API_KEY" if backend == "openrouter" else "NVIDIA_NIM_API_KEY"
            api_key = os.environ.get(env_var, "")
            if not api_key:
                print(f"  {YELLOW}⚠ No API key found. Set {env_var} env var or enter it now.{RST}")

    # ── Model name ──
    print()
    model_name = ""
    if backend == "ollama":
        model_name = input(f"  {PURP_L}Ollama model name (e.g. llama3, codellama, mistral):{RST} ").strip() or "llama3"
    elif backend == "openrouter":
        model_name = input(f"  {PURP_L}OpenRouter model (e.g. openai/gpt-4o, anthropic/claude-sonnet-4):{RST} ").strip()
    elif backend == "claude":
        model_name = input(f"  {PURP_L}Claude model (e.g. claude-sonnet-4-20250514):{RST} ").strip() or "claude-sonnet-4-20250514"
    elif backend == "nvidia_nim":
        model_name = input(f"  {PURP_L}NVIDIA NIM model name (e.g. meta/llama3-70b-instruct, nvidia/llama-3.1-nemotron):{RST} ").strip()

    # ── Token limits ──
    print()
    print(f"{PURP}┌{'─' * 56}┐{RST}")
    print(f"{PURP}│{RST}  {BOLD}TOKEN CONFIGURATION{RST}" + " " * 31 + f"{PURP}│{RST}")
    print(f"{PURP}├{'─' * 56}┤{RST}")
    print(f"{PURP}│{RST}  Set the maximum output tokens for this model.      {PURP}│{RST}")
    print(f"{PURP}│{RST}  Max tokens: capped at 50,000                       {PURP}│{RST}")
    print(f"{PURP}│{RST}  Leave blank for default (50,000)                   {PURP}│{RST}")
    print(f"{PURP}└{'─' * 56}┘{RST}")

    max_tokens: int | None = None
    min_tokens: int | None = None

    max_in = input(f"\n  {PURP_L}Maximum tokens (ENTER for 50000):{RST} ").strip()
    if max_in.isdigit():
        candidate = int(max_in)
        if candidate > 50000:
            print(f"  {YELLOW}⚠ Max tokens capped at 50,000. Setting to 50000.{RST}")
            max_tokens = 50000
        else:
            max_tokens = candidate
    else:
        max_tokens = 50000

    print()
    min_in = input(f"  {PURP_L}Minimum tokens (ENTER for 2000):{RST} ").strip()
    if min_in.isdigit():
        candidate = int(min_in)
        if candidate < 2000:
            print(f"  {YELLOW}⚠ Min tokens must be >= 2000. Setting to 2000.{RST}")
            min_tokens = 2000
        else:
            min_tokens = candidate
    else:
        min_tokens = 2000

    if min_tokens and max_tokens and min_tokens > max_tokens:
        print(f"  {YELLOW}⚠ Min tokens ({min_tokens}) > max tokens ({max_tokens}). Swapping.{RST}")
        min_tokens, max_tokens = max_tokens, min_tokens

    config = ModelConfig(
        backend=backend,
        model_name=model_name,
        api_key=api_key or None,
        nvidia_nim_url=nvidia_nim_url,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
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
            "min_tokens": min_tokens,
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
        print(f"{PURP}│{RST}  {PURP_L}🔢 Tokens:{RST} {WHITE}{usage.total_tokens:,}{RST} (in: {usage.input_tokens:,} | out: {usage.output_tokens:,})" + " " * 5 + f"{PURP}│{RST}")
    print(f"{PURP}└{'─' * 50}┘{RST}")
    print()


def is_conversational(user_input: str) -> bool:
    """Heuristic to detect if the user is just chatting vs asking for a command."""
    lower = user_input.strip().lower()
    chat_starters = (
        # Pure Q&A / learning
        "what is", "what are", "explain", "how does", "why is", "why does",
        "can you explain", "tell me about", "who is", "when", "where", "describe",
        "define", "meaning of", "difference between", "what's",
        "help me understand", "i want to understand", "i'm trying to learn",
        "teach me", "what are the",
        "is it possible to", "should i", "recommend", "suggest", "compare",
        "which is better", "pros and cons", "advice", "opinion", "thoughts on",
        "what do you think", "i need help",
        # Greetings & social
        "hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "goodbye", "bye", "see you", "cya", "good night",
        "who are you", "what can you do", "what do you do", "what's your name",
        "how are you", "what's up", "sup", "howdy", "how's it going",
        # Emotional / casual
        "i'm tired", "i'm bored", "i'm sad", "i'm happy", "i'm frustrated",
        "i feel", "lol", "haha", "nice", "cool", "awesome", "wow",
        "talk to me", "chat with me",
        # Meta questions
        "what model", "which model", "what llm",
        "what is the", "what does", "can i ask",
    )
    # Normalize contractions so "i am" matches "i'm" starters
    normalized = lower.replace("i am ", "i'm ").replace("i am", "i'm")
    if normalized.startswith(chat_starters):
        return True
    if lower.endswith("?"):
        return True
    # Short emotional / greeting messages (1-2 words)
    if len(lower.split()) <= 2 and lower in {
        "hi", "hello", "hey", "yo", "thanks", "bye", "ok", "okay", "cool",
        "nice", "wow", "lol", "haha", "yes", "no", "maybe", "sure", "yep", "nope",
        "good", "great", "awesome", "perfect",
    }:
        return True
    return False


def chat_reply(user_inp: str, config: ModelConfig, history: list[ChatMessage]) -> tuple[str, LLMUsage] | None:
    """Get a conversational reply from the model. Returns None on API failure."""
    prompt = build_chat_prompt(user_inp, ShellContext(cwd=os.getcwd(), env=dict(os.environ), os_name="windows" if os.name == "nt" else "linux"), history)
    try:
        reply, _, usage = ask_model_text(prompt, config, history)
    except RuntimeError as e:
        _handle_api_error(str(e))
        return None
    return reply, usage


def _handle_api_error(err_text: str) -> bool:
    """Print user-friendly message for common API errors. Returns True if handled."""
    err_lower = err_text.lower()
    if "401" in err_text or "unauthorized" in err_lower:
        print(f"\n  {BRIGHT_RED}✗ Authentication failed.{RST}")
        print(f"  {YELLOW}Your API key was rejected. Please check:{RST}")
        print(f"    1. Did you select the correct backend? (You chose: {config.backend})")
        if config.backend == "nvidia_nim":
            print(f"    2. NVIDIA NIM needs an NVIDIA API key (nvapi-...). Set NVIDIA_NIM_API_KEY env var.")
            print(f"    3. Or use a local NIM docker container instead of the cloud API.")
        elif config.backend == "openrouter":
            print(f"    2. OpenRouter needs an OpenRouter API key (sk-or-...). Set OPENROUTER_API_KEY env var.")
        elif config.backend == "claude":
            print(f"    2. Claude needs an Anthropic API key (sk-ant-...). Set ANTHROPIC_API_KEY env var.")
        print(f"\n  {CYAN}Run again and enter a valid API key when prompted.{RST}")
        return True
    elif "403" in err_text or "forbidden" in err_lower:
        print(f"\n  {BRIGHT_RED}✗ Access forbidden.{RST} Check that your API key has the correct permissions.")
        return True
    elif "429" in err_text or "rate" in err_lower:
        print(f"\n  {BRIGHT_YELLOW}⚠ Rate limited. Too many requests. Wait a minute and try again.{RST}")
        return True
    return False


def repl_loop(config: ModelConfig):
    context = ShellContext(
        cwd=os.getcwd(),
        env=dict(os.environ),
        os_name="windows" if os.name == "nt" else "linux",
    )
    history: list[ChatMessage] = []
    # Auto-confirm flag: cleared when a new command task starts, active during one task
    auto_confirm = False

    print_highlight_key_val("Backend", config.backend, PURP_L, WHITE)
    print_highlight_key_val("Model", config.model_name, PURP_L, WHITE)
    print_highlight_key_val("Max Tokens", str(config.max_tokens or "50000"), PURP_L, WHITE)
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
                print_highlight_key_val("Max Tokens", str(config.max_tokens or "50000"))
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
                    cfg = stored[name]
                    config = ModelConfig(
                        backend=cfg["backend"],
                        model_name=cfg["model_name"],
                        api_key=cfg.get("api_key"),
                        nvidia_nim_url=cfg.get("nvidia_nim_url"),
                        max_tokens=cfg.get("max_tokens"),
                        min_tokens=cfg.get("min_tokens"),
                        timeout=cfg.get("timeout", 900),
                    )
                    history = []
                    print(f"\n  {GREEN}✓ Switched to '{name}'. History cleared.{RST}")
                else:
                    print(f"\n  {YELLOW}⚠ Config '{name}' not found.{RST}")
                continue
            else:
                print(f"  {YELLOW}Unknown command. Type /help for available commands.{RST}")
                continue

        # ── History ──
        history.append(ChatMessage(role="user", content=user_inp))

        # ── Detect chat vs command ──
        if is_conversational(user_inp):
            # ── CHAT PATH ──
            spinner_start()
            try:
                result = chat_reply(user_inp, config, history)
            finally:
                spinner_stop()

            if result is None:
                # API error already printed by chat_reply, just skip
                continue

            reply, usage = result
            history.append(ChatMessage(role="assistant", content=reply))

            # No purple box for chat replies - just plain text
            print()
            print(f"  {BOLD}{PURP_L}🦊 ploxv1 says:{RST}")
            print(f"  {reply}")
            print_completion_block(usage)
            continue

        # ── COMMAND PATH ──
        is_repair = False
        failed_plan: CommandPlan | None = None
        failed_result: CommandExecutionResult | None = None

        while True:
            # Build prompt
            if is_repair:
                prompt = build_repair_prompt(user_inp, failed_plan, failed_result, context)
            else:
                prompt = build_command_prompt(user_inp, context, history)

            # Call model with error handling
            spinner_start()
            plan_dict = None
            reasoning = None
            usage = None

            try:
                plan_dict, reasoning, usage = ask_model_json(prompt, config, history)
            except RuntimeError as e:
                spinner_stop()
                _handle_api_error(str(e))
                break
            finally:
                if _spinner_running:
                    spinner_stop()

            if plan_dict is None or "error" in plan_dict:
                if not is_repair:
                    raw_text = plan_dict.get("raw", "") if plan_dict else ""
                    retry_prompt = (
                        prompt
                        + f"\n\n!!! YOUR LAST RESPONSE WAS NOT VALID JSON. You said:\n{raw_text[:300]}\n\n"
                        + "NOW OUTPUT ONLY VALID JSON. No markdown. No backticks. No explanation. ONLY the JSON object."
                    )
                    spinner_start()
                    try:
                        plan_dict, reasoning, usage2 = ask_model_json(retry_prompt, config, history)
                        if usage2:
                            usage = usage2
                    finally:
                        spinner_stop()

                if plan_dict is None or "error" in plan_dict:
                    raw_text = plan_dict.get("raw", "") if plan_dict else ""
                    print(f"\n  {BRIGHT_RED}✗ Model didn't return valid JSON after retry.{RST}")
                    if raw_text:
                        print(f"  {GREY}Raw: {raw_text[:300]}{RST}")
                    if not is_repair:
                        print_completion_block(usage)
                    break

            if reasoning:
                plan_dict["reasoning_details"] = reasoning

            commands = plan_dict.get("commands", [])

            if not commands:
                if not is_repair:
                    retry_prompt = (
                        prompt
                        + "\n\n!!! You returned valid JSON but 'commands' was EMPTY. "
                        + "Populate it with real shell commands the user needs."
                    )
                    spinner_start()
                    try:
                        plan_dict, reasoning, usage2 = ask_model_json(retry_prompt, config, history)
                        if usage2:
                            usage = usage2
                    finally:
                        spinner_stop()
                    commands = plan_dict.get("commands", []) if plan_dict and "error" not in plan_dict else []

                if not commands:
                    summary = plan_dict.get("summary", "No plan generated.") if plan_dict and "error" not in plan_dict else "No plan generated."
                    print()
                    print(f"  {BOLD}{YELLOW}⚠ Could not generate commands:{RST} {summary}")
                    print_completion_block(usage)
                    break

            plan = CommandPlan(
                domain=plan_dict.get("domain", "linux"),
                action=plan_dict.get("action", "unknown"),
                summary=plan_dict.get("summary", "No summary"),
                commands=commands,
                requires_confirmation=plan_dict.get("requires_confirmation", True),
                resolved_path=plan_dict.get("resolved_path"),
                warnings=plan_dict.get("warnings", []),
            )

            # Show plan - NO PURPLE BOX, just plain text with colors
            summary_color = BRIGHT_RED if plan.requires_confirmation else BRIGHT_GREEN
            confirm_label = "⚠ NEEDS CONFIRMATION" if plan.requires_confirmation else "✓ SAFE"

            print()
            print(f"  {BOLD}{PURP_L}📋 PLAN: {plan.action}{RST}")
            print(f"  {BLUE}Domain:{RST} {plan.domain}")
            print()
            print(f"  {PURP_L}Summary:{RST} {plan.summary}")
            print()
            print(f"  {CYAN}Commands to run:{RST}")
            for c in plan.commands:
                print(f"    {BRIGHT_BLUE}$ {c}{RST}")

            if plan.warnings:
                print()
                print(f"  {BRIGHT_YELLOW}⚠ Warnings:{RST}")
                for w in plan.warnings:
                    print(f"    {YELLOW}• {w}{RST}")

            print(f"\n  {summary_color}{confirm_label}{RST}")

            if plan.requires_confirmation:
                if not auto_confirm:
                    print(f"  {BRIGHT_GREEN}[Y]{RST} = Run it  {BRIGHT_RED}[N]{RST} = Cancel  {YELLOW}[E]{RST} = Edit  {PURP_L}[C]{RST} = Chat  {BRIGHT_GREEN}[A]{RST} = Yes to ALL this session")
                    decision = input(f"  {PURP_L}▶{RST} ").strip().lower()
                else:
                    # Already in auto-confirm mode
                    decision = "y"
                    print(f"  {DIM}[Auto-confirm: Yes to all]{RST}")
            else:
                if not auto_confirm:
                    print(f"  {BRIGHT_GREEN}[Y]{RST} = Run it  {BRIGHT_RED}[N]{RST} = Cancel  {PURP_L}[C]{RST} = Chat  {BRIGHT_GREEN}[A]{RST} = Yes to ALL")
                    decision = input(f"  {PURP_L}▶{RST} ").strip().lower()
                else:
                    decision = "y"
                    print(f"  {DIM}[Auto-confirm: Yes to all]{RST}")

            if decision in ("n", "no"):
                print(f"  {YELLOW}✗ Cancelled.{RST}")
                history.append(ChatMessage(role="assistant", content=f"[Plan was shown but user cancelled]: {plan.summary}"))
                print_completion_block(usage)
                break

            if decision == "a":
                auto_confirm = True
                print(f"  {GREEN}✓ Auto-confirm enabled for this task. All steps will run without asking.{RST}")
                decision = "y"

            if decision == "c":
                # Switch to chat mode - NO PURPLE BOX for chat
                chat_prompt = f"The user saw this plan and wants to chat instead:\n\nPlan: {plan.summary}\nCommands: {', '.join(plan.commands)}\n\nUser said: {user_inp}\n\nHave a conversation about this. Explain what the commands do, suggest alternatives, answer questions."
                spinner_start()
                try:
                    reply, _, chat_usage = ask_model_text(chat_prompt, config, history)
                finally:
                    spinner_stop()
                print()
                print(f"  {BOLD}{PURP_L}🦊 ploxv1 says:{RST}")
                print(f"  {reply}")
                history.append(ChatMessage(role="assistant", content=reply))
                print_completion_block(chat_usage)
                break

            if decision == "e" and plan.requires_confirmation:
                print(f"\n  {PURP_L}Commands to edit:{RST}")
                for i, c in enumerate(plan.commands):
                    print(f"  {BRIGHT_BLUE}[{i}]{RST} {c}")
                idx = input(f"  {PURP_L}Which command number to edit?{RST} ").strip()
                if idx.isdigit():
                    i = int(idx)
                    if 0 <= i < len(plan.commands):
                        new_cmd = input(f"  {PURP_L}New command:{RST} ").strip()
                        if new_cmd:
                            # Validate edited commands before accepting
                            if is_destructive(new_cmd):
                                print(f"  {YELLOW}⚠ Edited command flagged for safety review.{RST}")
                            plan.commands[i] = new_cmd
                            print(f"  {GREEN}✓ Updated.{RST}")
                # Re-show plan without purple box
                continue

            # ── Execute ──
            print(f"\n  {SPINNER_BLUE}⚡ Executing...{RST}")
            for i, cmd in enumerate(plan.commands):
                print(f"  {BRIGHT_BLUE}[{i+1}/{len(plan.commands)}]{RST} $ {cmd}")
                result = run_single_command(cmd)

                if result.returncode != 0:
                    print(f"  {BRIGHT_RED}  ✗ FAILED (code {result.returncode}){RST}")
                    if result.stderr.strip():
                        for line in result.stderr.strip().split("\n")[:5]:
                            print(f"  {RED}  | {line}{RST}")

                    # Offer repair
                    if not auto_confirm:
                        print()
                        repair_choice = input(f"  {YELLOW}Try to auto-repair? {BRIGHT_GREEN}[Y]{RST}/{BRIGHT_RED}[N]{RST}:{RST} ").strip().lower()
                    else:
                        print(f"  {GREEN}  [Auto-repairing...]{RST}")
                        repair_choice = "y"
                    if repair_choice in ("y", "yes", ""):
                        is_repair = True
                        failed_plan = plan
                        failed_result = result
                        break  # go back to while True for repair
                    else:
                        print(f"  {YELLOW}✗ Abandoned.{RST}")
                        break
                else:
                    if result.stdout.strip():
                        for line in result.stdout.strip().split("\n")[:10]:
                            print(f"  {DIM}  | {line}{RST}")
                    else:
                        print(f"  {GREEN}  ✓ OK{RST}")

                    # Update context.cwd if it was a cd command
                    if cmd.strip().startswith("cd "):
                        new_dir = cmd.strip()[3:].strip()
                        if os.path.isabs(new_dir):
                            context.cwd = new_dir
                        else:
                            context.cwd = os.path.normpath(os.path.join(context.cwd, new_dir))
                        os.chdir(context.cwd)

            if not is_repair or (plan.commands.index(cmd) == len(plan.commands) - 1 and result.returncode == 0):
                # Success on all commands
                history.append(ChatMessage(
                    role="assistant",
                    content=f"[Executed plan: {plan.action}]\nCommands:\n" + "\n".join(f"  $ {c}" for c in plan.commands)
                ))
                print_completion_block(usage)
                break
            else:
                # We're in repair mode, loop continues
                continue
        # End of while True (command loop)

        # Reset auto-confirm when a task completes or breaks out
        if auto_confirm:
            print(f"  {GREY}[Auto-confirm disabled — new task will ask again]{RST}")
        auto_confirm = False
