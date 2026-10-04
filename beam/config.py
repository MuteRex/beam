"""Persistent settings at ~/.config/beam/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "beam"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "provider": "tailscale",
    "resolution": "1920x1080",   # "" = Moonlight default
    "fps": 60,
    "bitrate": 0,                # Kbps, 0 = Moonlight auto
    "display_mode": "fullscreen",  # fullscreen / borderless / windowed
    "audio_config": "stereo",    # stereo / 5.1-surround / 7.1-surround
    "default_app": "Desktop",    # which Sunshine app to stream
    "multi_controller": True,
    "show_all_devices": False,   # False = only connectable hosts
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # keep only known keys, backfill new ones
    return {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2))
