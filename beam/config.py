"""Persistent settings at ~/.config/beam/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .options import DEFAULTS as ADVANCED_DEFAULTS

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "beam"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "provider": "auto",
    "resolution": "1920x1080",   # "" = Moonlight default
    "fps": 60,
    "bitrate": 0,                # Kbps, 0 = Moonlight auto
    "display_mode": "fullscreen",  # fullscreen / borderless / windowed
    "audio_config": "stereo",    # stereo / 5.1-surround / 7.1-surround
    "default_app": "Desktop",    # which Sunshine app to stream
    "multi_controller": True,
    "show_all_devices": False,   # False = only connectable hosts
    "mouse_mode": "desktop",     # desktop = cursor free (absolute);
                                 # game = cursor locked/relative
    "moonlight_bin": "",         # "" = auto: Beam fork, then system, then snap
    "show_pill": True,           # in-stream Beam pill (fork only)
    # Latency / quality. Always passed explicitly so Moonlight's own saved
    # preferences never silently change a stream.
    "video_codec": "auto",       # auto / H.264 / HEVC / AV1
    "video_decoder": "auto",     # auto / hardware / software
    "vsync": False,              # off = lowest latency, may tear
    "frame_pacing": False,       # on = smoother, adds up to a frame
    "stats_level": "off",        # off / basic / standard / advanced
    "prefer_lan": True,          # use the LAN IP when Tailscale is direct
    **ADVANCED_DEFAULTS,         # Settings → Advanced (see options.py)
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    saved = {}
    try:
        saved = json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    cfg.update(saved)
    # Old boolean overlay switch → stats level
    if "stats_level" not in saved and saved.get("performance_overlay"):
        cfg["stats_level"] = "standard"
    # keep only known keys, backfill new ones
    return {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2))
