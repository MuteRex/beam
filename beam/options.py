"""Advanced Moonlight options, defined once and used by both the Settings page
and the launcher, so the UI and the command line can't drift apart.

Every option is always passed explicitly (toggles as --x / --no-x) so Moonlight's
own saved preferences never silently change a Beam stream. Defaults match
Moonlight's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    key: str            # Beam config key
    kind: str           # "switch" | "choice" | "spin" | "entry"
    title: str
    subtitle: str
    default: object
    flag: str = ""      # Moonlight CLI option; "" = Beam-only
    choices: tuple = ()
    low: int = 0
    high: int = 0
    step: int = 1


# (group title, options) in the order they appear on the Advanced page
ADVANCED = [
    ("Video", [
        Option("custom_resolution", "entry", "Custom resolution",
               "e.g. 2560x1080, overrides General", "", "resolution"),
        Option("custom_fps", "spin", "Custom frame rate",
               "Any FPS, e.g. 75 or 100 to match a monitor; 0 = use General", 0,
               "fps", low=0, high=240, step=1),
        Option("hdr", "switch", "HDR",
               "10-bit HDR when the host display and codec support it", False, "hdr"),
        Option("yuv444", "switch", "YUV 4:4:4",
               "Sharper text and colour edges; needs host and decoder support", False, "yuv444"),
        Option("packet_size", "spin", "Video packet size",
               "Bytes per network packet; 0 = automatic. Lower can help on VPNs",
               0, "packet-size", low=0, high=1500, step=8),
    ]),
    ("Audio", [
        Option("audio_on_host", "switch", "Play audio on host",
               "Keep sound on the host's speakers instead of streaming it", False,
               "audio-on-host"),
        Option("mute_on_focus_loss", "switch", "Mute when window loses focus",
               "", False, "mute-on-focus-loss"),
    ]),
    ("Input", [
        Option("capture_system_keys", "choice", "Capture system shortcuts",
               "Send Super, Alt+Tab and similar keys to the host (Full immersion in the Beam menu toggles it mid-stream)",
               "fullscreen", "capture-system-keys", choices=("never", "fullscreen", "always")),
        Option("mouse_buttons_swap", "switch", "Swap mouse buttons", "", False,
               "mouse-buttons-swap"),
        Option("reverse_scroll", "switch", "Reverse scroll direction", "", False,
               "reverse-scroll-direction"),
        Option("touchscreen_trackpad", "switch", "Touchscreen as trackpad",
               "Relative pointer instead of tapping where you touch", False,
               "touchscreen-trackpad"),
        Option("swap_gamepad_buttons", "switch", "Nintendo-style gamepad buttons",
               "Swap A/B and X/Y", False, "swap-gamepad-buttons"),
        Option("background_gamepad", "switch", "Gamepad input in background",
               "Keep sending controller input when the stream isn't focused", False,
               "background-gamepad"),
    ]),
    ("Session", [
        Option("game_optimization", "switch", "Game optimizations",
               "Let the host adjust its settings for streaming", True, "game-optimization"),
        Option("quit_after", "switch", "Quit app on host after session",
               "Close the streamed app when you disconnect", False, "quit-after"),
        Option("keep_awake", "switch", "Keep display awake",
               "Prevent screen blanking while streaming", True, "keep-awake"),
    ]),
    ("Beam", [
        Option("host_screens", "spin", "Host screens",
               "Screen buttons in the in-stream Beam menu; Sunshine switches monitors mid-stream",
               2, low=1, high=12, step=1),
        Option("test_step_seconds", "spin", "Test connection step length",
               "Seconds measured at each bitrate step (5 steps at most)", 5,
               low=3, high=20, step=1),
    ]),
]

ALL = [o for _, group in ADVANCED for o in group]
DEFAULTS = {o.key: o.default for o in ALL}

_RESOLUTION = re.compile(r"^\d{3,5}x\d{3,5}$")


def valid_resolution(text: str) -> bool:
    return bool(_RESOLUTION.match((text or "").strip()))


def effective_resolution(config: dict) -> str:
    """Custom resolution when valid, otherwise the General preset ("" = auto)."""
    custom = (config.get("custom_resolution") or "").strip()
    if valid_resolution(custom):
        return custom
    return (config.get("resolution") or "").strip()


def resolution_size(config: dict) -> tuple[int, int]:
    res = effective_resolution(config)
    if not valid_resolution(res):
        return 1920, 1080
    w, h = res.split("x")
    return int(w), int(h)


def effective_fps(config: dict) -> int:
    """Custom frame rate when set, otherwise the General preset."""
    custom = int(config.get("custom_fps") or 0)
    return custom if custom > 0 else int(config.get("fps") or 60)


def cli_args(config: dict) -> list[str]:
    """Moonlight flags for every advanced option except custom resolution and
    frame rate, which the launcher folds into its video arguments."""
    args = []
    for o in ALL:
        if not o.flag or o.key in ("custom_resolution", "custom_fps"):
            continue
        value = config.get(o.key, o.default)
        if o.kind == "switch":
            args.append(f"--{o.flag}" if value else f"--no-{o.flag}")
        elif o.kind == "choice":
            args += [f"--{o.flag}", str(value if value in o.choices else o.default)]
        elif o.kind == "spin" and int(value or 0) > 0:
            args += [f"--{o.flag}", str(int(value))]
    return args
