"""Drives the Moonlight CLI: pair, list apps, stream.

Moonlight does the real streaming; Beam just builds the right command line from
the user's saved preferences and launches it without blocking the UI.
"""
from __future__ import annotations

import shutil
import subprocess

from gi.repository import Gio, GLib


def _moonlight_bin() -> str:
    for cand in ("moonlight", "/snap/bin/moonlight"):
        p = shutil.which(cand) or (cand if shutil.which(cand) else None)
        if p:
            return p
    return "moonlight"


class MoonlightLauncher:
    def __init__(self, config: dict):
        self.config = config
        self.bin = _moonlight_bin()

    # ---- command construction -------------------------------------------
    def _stream_args(self, address: str, app: str) -> list[str]:
        c = self.config
        args = [self.bin, "stream"]
        res = (c.get("resolution") or "").strip()
        if res:
            args += ["--resolution", res]
        if c.get("fps"):
            args += ["--fps", str(c["fps"])]
        if c.get("bitrate"):
            args += ["--bitrate", str(c["bitrate"])]
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
        args += [address, app]
        return args

    # ---- actions --------------------------------------------------------
    def stream(self, address: str, app: str | None = None) -> list[str]:
        """Launch a stream detached; returns the argv used (for logging)."""
        app = app or self.config.get("default_app") or "Desktop"
        args = self._stream_args(address, app)
        flags = (Gio.SubprocessFlags.STDOUT_SILENCE |
                 Gio.SubprocessFlags.STDERR_SILENCE)
        Gio.Subprocess.new(args, flags)
        return args

    def pair(self, address: str, pin: str) -> tuple[bool, str]:
        """Blocking pair. Run off the main thread. Returns (ok, message)."""
        try:
            out = subprocess.run(
                [self.bin, "pair", address, "--pin", pin],
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
                [self.bin, "list", address],
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
