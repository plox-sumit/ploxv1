import json
import os
import stat

import pytest

import ploxv1
from ploxv1 import cli, repl


def test_version_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ploxv1", "--version"])
    with pytest.raises(SystemExit):
        cli.main()
    assert capsys.readouterr().out.strip() == f"ploxv1 {ploxv1.__version__}"


def test_min_tokens_flag_is_gone(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ploxv1", "--backend", "ollama", "--min-tokens", "2000"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "unrecognized arguments" in capsys.readouterr().err


def test_saved_config_round_trip(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(repl, "CONFIG_PATH", str(path))

    repl.save_stored_configs({"café-server": {"backend": "ollama", "model_name": "llama3", "min_tokens": 2000}})

    assert json.loads(path.read_text(encoding="utf-8"))["café-server"]["backend"] == "ollama"
    config = repl.config_from_stored(repl.load_stored_configs()["café-server"])
    assert (config.backend, config.model_name, config.max_tokens) == ("ollama", "llama3", None)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
