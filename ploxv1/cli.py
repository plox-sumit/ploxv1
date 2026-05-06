import argparse
import sys

from .repl import (
    setup_model, repl_loop, list_stored_configs,
    load_stored_configs, delete_stored_config, print_welcome,
)
from .models import ModelConfig


def main():
    parser = argparse.ArgumentParser(
        prog="ploxv1",
        description="🦊 PloxV1 — Natural language to Linux & AWS CLI, powered by AI",
    )
    parser.add_argument("--backend", "-b", choices=["ollama", "openrouter", "claude", "nvidia_nim"], help="AI backend")
    parser.add_argument("--model", "-m", help="Model name")
    parser.add_argument("--api-key", "-k", help="API key")
    parser.add_argument("--nvidia-nim-url", help="Custom NVIDIA NIM endpoint URL")
    parser.add_argument("--max-tokens", type=int, help="Maximum tokens for responses (default: 50000)")
    parser.add_argument("--min-tokens", type=int, help="Minimum tokens for responses (min 2000, default: 2000)")
    parser.add_argument("--list-configs", action="store_true", help="List stored configurations")
    parser.add_argument("--delete-config", help="Delete a stored configuration by name")
    parser.add_argument("--use-config", help="Load a stored configuration by name")

    args = parser.parse_args()

    # ── List stored configs ──
    if args.list_configs:
        list_stored_configs()
        return

    # ── Delete a stored config ──
    if args.delete_config:
        delete_stored_config(args.delete_config)
        return

    # ── Use a stored config ──
    if args.use_config:
        stored = load_stored_configs()
        if args.use_config in stored:
            cfg = stored[args.use_config]
            config = ModelConfig(
                backend=cfg["backend"],
                model_name=cfg["model_name"],
                api_key=cfg.get("api_key"),
                nvidia_nim_url=cfg.get("nvidia_nim_url"),
                max_tokens=cfg.get("max_tokens"),
                min_tokens=cfg.get("min_tokens"),
            )
            repl_loop(config)
            return
        else:
            print(f"Config '{args.use_config}' not found. Use --list-configs to see available ones.")
            sys.exit(1)

    # ── CLI-specified config ──
    if args.backend:
        max_tok = args.max_tokens
        min_tok = args.min_tokens

        # Validate min/max tokens
        if min_tok is not None and min_tok < 2000:
            print(f"Warning: --min-tokens must be >= 2000. Setting to 2000.")
            min_tok = 2000
        if max_tok is not None and min_tok is not None and min_tok > max_tok:
            print(f"Warning: min_tokens ({min_tok}) > max_tokens ({max_tok}). Swapping them.")
            max_tok, min_tok = min_tok, max_tok

        config = ModelConfig(
            backend=args.backend,
            model_name=args.model or "",
            api_key=args.api_key,
            nvidia_nim_url=args.nvidia_nim_url,
            max_tokens=max_tok,
            min_tokens=min_tok,
        )
    else:
        # ── Show animated logo, then interactive setup ──
        print_welcome()
        config = setup_model()

    repl_loop(config)


if __name__ == "__main__":
    main()
