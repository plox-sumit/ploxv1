# PloxV1 — Your Terminal AI Companion

Turn plain English into Linux commands, AWS CLI operations, and more. Chat naturally or execute tasks — all from your terminal.

## What It Does

- **Chat Mode**: Ask questions about shell, Linux, AWS, programming, or just chat
- **Command Mode**: Describe what you want, get shell commands to run
- **Multi-Backend**: Works with Ollama (free, local), OpenRouter, Claude, or NVIDIA NIM
- **Smart Safety**: Warns before destructive commands (`rm`, `sudo`, etc.)
- **Auto-Repair**: If a command fails, it analyzes and suggests a fix
- **Cross-Platform**: Works on Linux, WSL, and Windows (PowerShell)

## Quick Start

### Install

Needs Python 3.11 or newer.

```bash
# With pipx (recommended: keeps PloxV1 in its own environment)
pipx install git+https://github.com/plox-sumit/ploxv1.git

# Or with pip
pip install git+https://github.com/plox-sumit/ploxv1.git
```

The Claude backend needs one extra package. Add it only if you use Claude:

```bash
pipx inject ploxv1 anthropic     # if you installed with pipx
pip install anthropic            # if you installed with pip
```

### Run

```bash
# Interactive setup (choose backend, model, save config)
ploxv1

# Or directly with a backend
ploxv1 --backend ollama --model llama3

# Check what you have installed
ploxv1 --version
```

### Work on the code

```bash
git clone https://github.com/plox-sumit/ploxv1.git
cd ploxv1
pip install -e ".[dev]"

pytest          # nothing goes over the network
ruff check .
```

## AI Backends

| Backend | Needs API Key? | Best For |
|---------|---------------|----------|
| **Ollama** | No | Free, offline, local models |
| **OpenRouter** | Yes (sk-or-...) | 200+ cloud models |
| **Claude** | Yes (sk-ant-...) | Best reasoning |
| **NVIDIA NIM** | Yes (nvapi-...) | Fast GPU inference |

### API Key Setup

```bash
# OpenRouter
export OPENROUTER_API_KEY="sk-or-..."

# Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# NVIDIA NIM
export NVIDIA_NIM_API_KEY="nvapi-..."
```

A key passed with `--api-key` or saved in a config is used first. A NIM container you run yourself (`--nvidia-nim-url http://localhost:8000/v1/chat/completions`) needs no key.

## How to Use

Just type. The model works out whether you asked a question or want something done, so "what's using port 8080?" gets a command and "what is docker?" gets an answer.

### Chat
```
🦊 You: what is docker?

🦊 ploxv1 says:
Docker is a tool that packages software into containers...
```

### Commands
```
🦊 You: list all running containers

  📋 PLAN: List all running Docker containers

  Commands to run:
    $ docker ps

  ✓ SAFE
  [Y] = Run it  [N] = Cancel  [E] = Edit  [C] = Chat  [A] = Yes to ALL this task
  ▶ y

  ⚡ Executing...
  [1/1] $ docker ps
    | CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES
```

Output is shown line by line while the command runs, and PloxV1 remembers the end of it, so you can ask "what does that mean?" next. Press Ctrl+C to stop a command that is taking too long.

Commands can't ask you questions while they run. A command that needs typing (a `[Y/n]` prompt, an editor) fails straight away, so ask for the non-interactive form, such as `apt-get install -y`.

### Slash Commands

| Command | Action |
|---------|--------|
| `/help` | Show help |
| `/exit` | Quit |
| `/clear` | Clear history |
| `/config` | Show current setup |
| `/stored` | List saved configs |
| `/switch` | Switch to another saved config |

### Confirmation Options

When a plan is shown, you can:
- **Y** — Run it
- **N** — Cancel
- **E** — Edit a command
- **C** — Chat about it
- **A** — Yes to ALL (auto-confirm the rest of this task; destructive commands still ask)

Anything else, including just pressing Enter, cancels.

## Persistent Configs

Save your setup so you don't type it again:

```bash
# During setup, say YES to "Store this configuration?"
# Later, use it directly:
ploxv1 --use-config my-server
```

## Safety

- **Nothing runs until you say Y.** Every plan is shown first
- **PloxV1 checks each command itself**, it does not take the AI's word for it:
  - destructive commands (`rm`, `sudo`, `dd`, `>` into a file, `curl ... | sh`) are marked in red
  - a plan is marked `✓ SAFE` only when every command is read-only (`ls`, `cat`, `grep`)
- **Yes to ALL never covers destructive commands**
- **Auto-repair stops after 3 tries**
- **Edited commands** are checked again before they run
- **API keys** you save are stored in `~/.ploxv1_config.json` with `0o600` permissions (owner-only). Leave the key blank during setup to keep it out of the file and read it from the environment instead

PloxV1 runs each command through a real shell (`bash -c`, or `powershell -Command` on Windows), so a command can do anything you could do by typing it. The checks above are what stand between the AI and your machine. Read the plan before you press Y.

## File Overview

```
ploxv1/
├── cli.py           # Entry point, argument parsing
├── llm.py           # Talks to AI backends (Ollama, OpenRouter, Claude, NVIDIA)
├── models.py        # Data classes (config, messages, plans)
├── repl.py          # Main loop — chat, command execution, UI
├── executor.py      # Runs one command in bash / PowerShell and streams its output
├── safety.py        # Picks the shell; tells destructive and read-only commands apart
├── prompting.py     # The prompt: the model answers with commands or with a reply
├── repair_prompting.py  # Repair prompts when commands fail
└── __init__.py      # Package info and version
tests/               # pytest suite
```

## License

MIT — free to use, modify, and share.
