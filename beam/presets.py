"""Quick settings, like Parsec's: one click sets codec, home bitrate, V-Sync and
frame pacing together. Away bitrate and per-computer values still apply."""
from __future__ import annotations

KEYS = ("video_codec", "bitrate", "vsync", "frame_pacing")

# (id, label, tooltip, values)
PRESETS = [
    ("latency", "Latency", "H.264, 20 Mbps, no V-Sync or frame pacing: the fastest response",
     {"video_codec": "H.264", "bitrate": 20000, "vsync": False, "frame_pacing": False}),
    ("balanced", "Balanced", "Beam's defaults: automatic codec and bitrate, no V-Sync or frame pacing",
     {"video_codec": "auto", "bitrate": 0, "vsync": False, "frame_pacing": False}),
    ("quality", "Quality", "HEVC, 50 Mbps, V-Sync and frame pacing: the sharpest, smoothest picture",
     {"video_codec": "HEVC", "bitrate": 50000, "vsync": True, "frame_pacing": True}),
]


def values(preset_id: str) -> dict:
    return dict(next(v for i, _l, _t, v in PRESETS if i == preset_id))


def matching(settings: dict) -> str | None:
    """The preset these settings are exactly, else None (a custom mix)."""
    for preset_id, _label, _tip, vals in PRESETS:
        if all(settings.get(k) == v for k, v in vals.items()):
            return preset_id
    return None
