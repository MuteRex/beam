"""Drives the Moonlight CLI: pair, list apps, stream.

Moonlight does the real streaming; Beam just builds the right command line from
the user's saved preferences and launches it without blocking the UI.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Gio, GLib

from . import bitrate, options, probe


# Self-built Moonlight fork with the in-stream Beam pill
FORK_BIN = Path.home() / "beam-moonlight" / "app" / "moonlight"

LOG_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "beam" / "logs"
LOGS_KEPT = 20

# Sunshine's built-in remote desktop app. Ending it on disconnect loses nothing
# (there is nothing to resume) and runs any undo hooks the host has set up.
DESKTOP_APP = "Desktop"


@dataclass
class StreamResult:
    """How a stream ended, read from Moonlight's log."""
    address: str
    app: str
    log_path: Path
    clean: bool           # ended by the user, not by an error or a drop
    message: str          # one line for the user; "" when there's nothing to say
    delivered_fps: float | None = None  # frames/s that arrived from the host


# Common display refresh rates, for reading a host's limit off its frame rate
REFRESH_RATES = (30, 48, 50, 60, 72, 75, 90, 100, 120, 144, 165, 240)


def host_refresh_limit(delivered: float | None, requested: int) -> int | None:
    """The refresh rate a host is evidently capped at, or None if it kept up or
    the reading is inconclusive (e.g. a mostly idle desktop sending few frames).
    """
    if not delivered or delivered >= requested * 0.9:
        return None
    rate = min(REFRESH_RATES, key=lambda r: abs(r - delivered))
    return rate if abs(delivered - rate) <= rate * 0.08 and rate < requested else None


# Moonlight log lines -> what to tell the user, in priority order
_FAILURES = [
    (r"has not been paired", "{host} isn't paired yet. Use ⋯ → Pair with host…"),
    (r"Failed to connect to", "Couldn't reach {host}."),
    (r"Failed to find application", "{host} has no app called “{app}”."),
    (r"Connection terminated: -100\b", "No video arrived from {host}; check its firewall."),
    (r"Connection terminated: -?[1-9]", "The connection to {host} dropped."),
]


def read_result(address: str, app: str, log_path: Path, host_name: str = "") -> StreamResult:
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        text = ""
    host = host_name or address
    stats = text.split("Global video stats", 1)
    fps = re.search(r"Incoming frame rate from network: ([\d.]+)", stats[1]) if len(stats) == 2 else None
    delivered = float(fps.group(1)) if fps else None
    for pattern, message in _FAILURES:
        if re.search(pattern, text):
            return StreamResult(address, app, log_path, False, message.format(host=host, app=app),
                                delivered)
    started = "Connection terminated" in text or len(stats) == 2
    return StreamResult(address, app, log_path, True,
                        f"Disconnected from {host}." if started else "", delivered)


def _new_log_path(address: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOG_DIR.chmod(0o700)  # logs name your hosts and their addresses
    logs = sorted(LOG_DIR.glob("stream-*.log"))
    for old in logs[:max(0, len(logs) - LOGS_KEPT + 1)]:
        old.unlink(missing_ok=True)
    safe = re.sub(r"[^A-Za-z0-9.-]", "_", address)
    return LOG_DIR / f"stream-{time.strftime('%Y%m%d-%H%M%S')}-{safe}.log"


def resolve_moonlight_bin(configured: str = "") -> str:
    """Configured path if usable, else the Beam fork, else system/snap."""
    configured = os.path.expanduser((configured or "").strip())
    if configured and os.access(configured, os.X_OK):
        return configured
    if os.access(FORK_BIN, os.X_OK):
        return str(FORK_BIN)
    for cand in ("moonlight", "/snap/bin/moonlight"):
        p = shutil.which(cand)
        if p:
            return p
    return "moonlight"


def is_fork(path: str) -> bool:
    return Path(path).resolve() == FORK_BIN.resolve()


class MoonlightLauncher:
    def __init__(self, config: dict):
        self.config = config

    @property
    def bin(self) -> str:
        # Resolved per call so a Settings change applies without a restart
        return resolve_moonlight_bin(self.config.get("moonlight_bin", ""))

    # ---- command construction -------------------------------------------
    def bitrate_for(self, address: str | None = None, host_key: str | None = None) -> int:
        """Kbps to ask for (0 = Moonlight's automatic choice); see bitrate.choose.
        No address (the benchmark) means the Home bitrate as configured."""
        if address is None:
            return int(self.config.get("bitrate") or 0)
        route = bitrate.route_of(probe.is_lan_address(address))
        return bitrate.choose(self.config, route, host_key)

    def video_args(self, address: str | None = None, host_key: str | None = None) -> list[str]:
        """Options that shape the video pipeline (shared with the benchmark)."""
        c = self.config
        args = []
        res = options.effective_resolution(c)
        if res:
            args += ["--resolution", res]
        args += ["--fps", str(options.effective_fps(c))]
        kbps = self.bitrate_for(address, host_key)
        if kbps:
            args += ["--bitrate", str(kbps)]
        args += ["--video-codec", c.get("video_codec") or "auto",
                 "--video-decoder", c.get("video_decoder") or "auto"]
        args.append("--vsync" if c.get("vsync") else "--no-vsync")
        args.append("--frame-pacing" if c.get("frame_pacing") else "--no-frame-pacing")
        return args

    def _stream_args(self, address: str, app: str, host_key: str | None = None) -> list[str]:
        c = self.config
        if app == DESKTOP_APP:
            c = dict(c, quit_after=True)
        args = [self.bin, "stream", *self.video_args(address, host_key), *options.cli_args(c)]
        stats = c.get("stats_level") or "off"
        args.append("--no-performance-overlay" if stats == "off" else "--performance-overlay")
        if c.get("display_mode"):
            args += ["--display-mode", c["display_mode"]]
        # Mouse: desktop = remote-desktop optimized (cursor free, can leave the
        # window); game = captured/relative (locked to the window, needed for
        # mouselook).
        if c.get("mouse_mode", "desktop") == "desktop":
            args += ["--absolute-mouse"]
        else:
            args += ["--no-absolute-mouse"]
        if c.get("audio_config"):
            args += ["--audio-config", c["audio_config"]]
        if c.get("multi_controller"):
            args += ["--multi-controller"]
        # "--" so host-supplied app names can't be parsed as options
        args += ["--", address, app]
        return args

    # ---- actions --------------------------------------------------------
    def address_for(self, host) -> str:
        """Fastest route to the host: its LAN address (found locally, or a
        Tailscale peer that is directly on our LAN) unless LAN preference is
        off, then the tailnet address."""
        routes = host.extra.get("routes") or []
        lan = next((r["address"] for r in routes if r["kind"] == "lan"), "") \
            or host.extra.get("lan_address", "")
        tailnet = next((r["address"] for r in routes if r["kind"] == "tailscale"), "")
        if lan and self.config.get("prefer_lan", True):
            return lan
        return tailnet or lan or host.address

    def fork_env(self, display_pos: tuple[int, int] | None = None) -> dict[str, str]:
        """Environment the fork reads for its in-stream menu and stats."""
        env = {}
        if not self.config.get("show_pill", True):
            env["BEAM_HIDE_PILL"] = "1"
        if (self.config.get("stats_level") or "off") != "off":
            # The fork's stats panel level (it cycles in-stream from the Beam menu)
            env["BEAM_STATS_LEVEL"] = self.config["stats_level"]
        # Screen buttons in the fork's menu (Sunshine's Ctrl+Alt+Shift+F1..F12)
        screens = self.config.get("host_screens") or 2
        env["BEAM_SCREENS"] = str(max(1, min(12, int(screens))))
        if display_pos is not None:
            # The fork opens the stream on this monitor (Wayland can't tell it)
            env["BEAM_DISPLAY_POS"] = "%d,%d" % display_pos
        return env

    def stream(self, address: str, app: str | None = None,
               display_pos: tuple[int, int] | None = None,
               on_exit=None, host_name: str = "", host_key: str | None = None) -> Path:
        """Launch a stream without blocking. Moonlight's output goes to a log
        file (returned); `on_exit(StreamResult)` runs on the main loop when the
        stream ends."""
        if not probe.valid_address(address):
            raise ValueError(f"not a valid host address: {address!r}")
        app = app or self.config.get("default_app") or DESKTOP_APP
        args = self._stream_args(address, app, host_key)
        log_path = _new_log_path(address)
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_stdout_file_path(str(log_path))
        for name, value in self.fork_env(display_pos).items():
            launcher.setenv(name, value, True)
        proc = launcher.spawnv(args)

        def done(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error:
                pass
            if on_exit is not None:
                on_exit(read_result(address, app, log_path, host_name))

        proc.wait_async(None, done)
        return log_path

    def end_session(self, address: str) -> bool:
        """Blocking: quit whatever app the host is running (`moonlight quit`).
        Run off the main thread."""
        if not probe.valid_address(address):
            return False
        try:
            out = subprocess.run([self.bin, "quit", "--", address],
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return out.returncode == 0

    @staticmethod
    def host_busy(address: str) -> bool:
        """True while the host still has a session (running app)."""
        info = probe.server_info(address, timeout=3) or {}
        return info.get("state", "").endswith("_BUSY")

    def pair(self, address: str, pin: str) -> tuple[bool, str]:
        """Blocking pair. Run off the main thread. Returns (ok, message)."""
        if not probe.valid_address(address):
            return False, "Not a valid host address."
        try:
            out = subprocess.run(
                [self.bin, "pair", "--pin", pin, "--", address],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            return False, "Moonlight is not installed."
        except subprocess.TimeoutExpired:
            return False, "Pairing timed out."
        ok = out.returncode == 0
        msg = (out.stdout + out.stderr).strip().splitlines()
        msg = next((l for l in reversed(msg) if l.strip()), "") if msg else ""
        return ok, msg

    def list_apps(self, address: str) -> list[str]:
        """Blocking app list. Run off the main thread."""
        if not probe.valid_address(address):
            return []
        try:
            out = subprocess.run(
                [self.bin, "list", "--", address],
                capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        if out.returncode != 0:
            return []
        apps = []
        for line in out.stdout.splitlines():
            line = line.strip()
            # Moonlight prints one app name per line; skip its log noise.
            if line and not any(t in line for t in ("SDL ", "Qt ", "libEGL",
                                                    "amdgpu", "XDG")):
                apps.append(line)
        return apps
