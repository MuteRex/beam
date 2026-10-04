"""Drives the Moonlight CLI: pair, list apps, stream.

Moonlight does the real streaming; Beam just builds the right command line from
the user's saved preferences and launches it without blocking the UI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from gi.repository import Gio, GLib

from . import options


# Self-built Moonlight fork with the in-stream Beam pill (see FORK_PLAN.md)
FORK_BIN = Path.home() / "beam-moonlight" / "app" / "moonlight"


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
    def video_args(self) -> list[str]:
        """Options that shape the video pipeline (shared with the benchmark)."""
        c = self.config
        args = []
        res = (c.get("resolution") or "").strip()
        custom = (c.get("custom_resolution") or "").strip()
        if options.valid_resolution(custom):
            res = custom
        if res:
            args += ["--resolution", res]
        args += ["--fps", str(options.effective_fps(c))]
        if c.get("bitrate"):
            args += ["--bitrate", str(c["bitrate"])]
        args += ["--video-codec", c.get("video_codec") or "auto",
                 "--video-decoder", c.get("video_decoder") or "auto"]
        args.append("--vsync" if c.get("vsync") else "--no-vsync")
        args.append("--frame-pacing" if c.get("frame_pacing") else "--no-frame-pacing")
        return args

    def _stream_args(self, address: str, app: str) -> list[str]:
        c = self.config
        args = [self.bin, "stream", *self.video_args(), *options.cli_args(c)]
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

    def stream(self, address: str, app: str | None = None,
               display_pos: tuple[int, int] | None = None) -> list[str]:
        """Launch a stream detached; returns the argv used (for logging)."""
        app = app or self.config.get("default_app") or "Desktop"
        args = self._stream_args(address, app)
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_SILENCE |
            Gio.SubprocessFlags.STDERR_SILENCE)
        if not self.config.get("show_pill", True):
            launcher.setenv("BEAM_HIDE_PILL", "1", True)
        if (self.config.get("stats_level") or "off") != "off":
            # The fork's stats panel level (it cycles in-stream from the Beam menu)
            launcher.setenv("BEAM_STATS_LEVEL", self.config["stats_level"], True)
        if display_pos is not None:
            # The fork opens the stream on this monitor (Wayland can't tell it)
            launcher.setenv("BEAM_DISPLAY_POS", "%d,%d" % display_pos, True)
        launcher.spawnv(args)
        return args

    def pair(self, address: str, pin: str) -> tuple[bool, str]:
        """Blocking pair. Run off the main thread. Returns (ok, message)."""
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
