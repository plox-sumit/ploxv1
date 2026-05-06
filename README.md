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

```bash
# 1. Copy to your machine
cp -r /mnt/c/Users/SUMIT/Downloads/ploxv1-main ~/ploxv1
cd ~/ploxv1

# 2. Install (Python 3.11+)
pip install -e .
```

### Run

```bash
# Interactive setup (choose backend, model, save config)
ploxv1

# Or directly with a backend
ploxv1 --backend ollama --model llama3
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

## How to Use

### Chat
```
🦊 You: what is docker?

🦊 ploxv1 says:
Docker is a tool that packages software into containers...
```

### Commands
```
🦊 You: list all running containers

  📋 PLAN: list running containers
  Domain: linux
  Summary: List all Docker containers
  Commands to run:
    $ docker ps

  ✓ SAFE

  [Y] = Run it  [N] = Cancel  [C] = Chat  [A] = Yes to ALL this session
  ▶ y
```

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
- **A** — Yes to ALL (auto-confirm every step in this task)

## Persistent Configs

Save your setup so you don't type it again:

```bash
# During setup, say YES to "Store this configuration?"
# Later, use it directly:
ploxv1 --use-config my-server
```

## Safety

- **Destructive commands** (`rm`, `sudo`, `dd`) require confirmation
- **Read-only commands** (`ls`, `cat`, `grep`) run without asking
- **Edited commands** are re-checked for safety
- **API keys** stored in `~/.ploxv1_config.json` with `0o600` permissions (owner-only)

## File Overview

```
ploxv1/
├── cli.py           # Entry point, argument parsing
├── llm.py           # Talks to AI backends (Ollama, OpenRouter, Claude, NVIDIA)
├── models.py        # Data classes (config, messages, plans)
├── repl.py          # Main loop — chat, command execution, UI
├── executor.py      # Runs shell commands safely
├── safety.py        # Detects dangerous commands
├── prompting.py     # Prompts for AI (commands, chat)
├── repair_prompting.py  # Repair prompts when commands fail
└── __init__.py      # Package info
```

## License

MIT — free to use, modify, and share.
