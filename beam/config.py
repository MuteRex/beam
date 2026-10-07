"""Persistent settings at ~/.config/beam/config.json."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .options import DEFAULTS as ADVANCED_DEFAULTS

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "beam"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "provider": "auto",
    "resolution": "1920x1080",   # "" = Moonlight default
    "fps": 60,
    "bitrate": 0,                # Kbps, 0 = Moonlight auto
    "away_bitrate": 8000,        # Kbps cap off the home network, 0 = no cap
    # From Test connection: {host key: {"name", "home": kbps, "away": kbps}}
    "host_bitrates": {},
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
    # Learned per host from the end-of-stream stats: {host key: {"fps", "name"}}
    # for hosts that delivered fewer frames than asked (their screen's refresh)
    "host_fps": {},
    "fps_warning_muted": [],     # host keys: "Don't show again" on the fps warning
    **ADVANCED_DEFAULTS,         # Settings → Advanced (see options.py)
}


def _coerce(key: str, value):
    """`value` if it has the same type as the default, else the default. A
    hand-edited or old config must never crash the app or reach the command line
    as the wrong type."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if key == "host_fps" and isinstance(value, dict):
        return {k: {"fps": v["fps"], "name": v.get("name", "") if isinstance(v.get("name"), str) else ""}
                for k, v in value.items()
                if isinstance(k, str) and isinstance(v, dict)
                and isinstance(v.get("fps"), int) and not isinstance(v.get("fps"), bool)
                and 1 <= v["fps"] <= 1000}
    if key == "host_bitrates" and isinstance(value, dict):
        clean = {}
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            entry = {"name": v.get("name") if isinstance(v.get("name"), str) else ""}
            for route in ("home", "away"):
                kbps = v.get(route)
                if isinstance(kbps, int) and not isinstance(kbps, bool) and 0 < kbps <= 1_000_000:
                    entry[route] = kbps
            if "home" in entry or "away" in entry:
                clean[k] = entry
        return clean
    if key == "fps_warning_muted" and isinstance(value, list):
        return [k for k in value if isinstance(k, str)]
    return default


def load() -> dict:
    saved = {}
    try:
        saved = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        pass
    if not isinstance(saved, dict):
        saved = {}
    cfg = {k: _coerce(k, saved[k]) if k in saved else DEFAULTS[k] for k in DEFAULTS}
    # Old boolean overlay switch → stats level
    if "stats_level" not in saved and saved.get("performance_overlay"):
        cfg["stats_level"] = "standard"
    return cfg


def save(cfg: dict) -> None:
    """Atomic, owner-only write: a crash mid-save can't leave a corrupt file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    clean = {k: _coerce(k, cfg.get(k, DEFAULTS[k])) for k in DEFAULTS}
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        os.unlink(tmp)
        raise
