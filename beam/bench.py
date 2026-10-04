"""Headless latency benchmark: streams from a host inside an invisible Weston
compositor (real EGL + VAAPI path, nothing on screen) and collects Moonlight's
end-of-session stats.

    python3 -m beam.bench 192.168.68.117                 # default matrix
    python3 -m beam.bench 192.168.68.117 --seconds 30 --only codec
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .launcher import resolve_moonlight_bin

STAT_PATTERNS = {
    "net_fps": r"Incoming frame rate from network: ([\d.]+)",
    "render_fps": r"Rendering frame rate: ([\d.]+)",
    "host_ms": r"Host processing latency min/max/average: [\d.]+/[\d.]+/([\d.]+)",
    "host_max_ms": r"Host processing latency min/max/average: [\d.]+/([\d.]+)/",
    "net_drop_pct": r"Frames dropped by your network connection: ([\d.]+)",
    "jitter_drop_pct": r"Frames dropped due to network jitter: ([\d.]+)",
    "net_ms": r"Average network latency: (\d+) ms",
    "net_var_ms": r"Average network latency: \d+ ms \(variance: (\d+) ms\)",
    "decode_ms": r"Average decoding time: ([\d.]+)",
    "queue_ms": r"Average frame queue delay: ([\d.]+)",
    "render_ms": r"Average rendering time \(including monitor V-sync latency\): ([\d.]+)",
}


@dataclass
class Case:
    name: str
    args: list[str] = field(default_factory=list)
    group: str = "base"


@dataclass
class Result:
    case: Case
    stats: dict[str, float]
    codec: str
    error: str = ""

    @property
    def total_ms(self) -> float | None:
        """Estimated glass-to-glass excluding capture/display scanout."""
        s = self.stats
        if not all(k in s for k in ("host_ms", "net_ms", "decode_ms", "queue_ms", "render_ms")):
            return None
        return s["host_ms"] + s["net_ms"] + s["decode_ms"] + s["queue_ms"] + s["render_ms"]


def default_cases(base_res: str, fps: int) -> list[Case]:
    common = ["--resolution", base_res, "--fps", str(fps)]
    return [
        Case("baseline (auto codec, auto bitrate)", common, "base"),
        Case("H.264", common + ["--video-codec", "H.264"], "codec"),
        Case("HEVC", common + ["--video-codec", "HEVC"], "codec"),
        Case("AV1", common + ["--video-codec", "AV1"], "codec"),
        Case("bitrate 10 Mbps", common + ["--bitrate", "10000"], "bitrate"),
        Case("bitrate 40 Mbps", common + ["--bitrate", "40000"], "bitrate"),
        Case("720p", ["--resolution", "1280x720", "--fps", str(fps)], "resolution"),
        Case("120 fps", ["--resolution", base_res, "--fps", "120"], "fps"),
    ]


class HeadlessCompositor:
    def __init__(self, width: int, height: int):
        self.socket = f"beam-bench-{os.getpid()}"
        self.width, self.height = width, height
        self.proc = None

    def __enter__(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.proc = subprocess.Popen(
            ["weston", "--backend=headless", "--renderer=gl",
             f"--width={self.width}", f"--height={self.height}",
             f"--socket={self.socket}", "--idle-time=0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sock = Path(runtime) / self.socket
        for _ in range(50):
            if sock.exists():
                return self
            time.sleep(0.1)
        self.__exit__()
        raise RuntimeError("headless weston did not start (is weston installed?)")

    def __exit__(self, *_):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(WAYLAND_DISPLAY=self.socket, QT_QPA_PLATFORM="wayland",
                   SDL_VIDEODRIVER="wayland", BEAM_HIDE_PILL="1")
        env.pop("DISPLAY", None)
        return env


def run_case(binary: str, host: str, app: str, case: Case, seconds: int,
             compositor: HeadlessCompositor) -> Result:
    with tempfile.NamedTemporaryFile("w+", suffix=".log") as log:
        proc = subprocess.Popen(
            [binary, "stream", "--display-mode", "fullscreen", *case.args, "--", host, app],
            stdout=log, stderr=subprocess.STDOUT, env=compositor.env())
        try:
            proc.wait(timeout=seconds)
            ended_early = True
        except subprocess.TimeoutExpired:
            ended_early = False
            # A single SIGTERM makes Moonlight quit cleanly and print its stats;
            # a second one exits immediately without them.
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        log.seek(0)
        text = log.read()

    stats = {}
    block = text.split("Global video stats", 1)
    if len(block) == 2:
        for key, pattern in STAT_PATTERNS.items():
            m = re.search(pattern, block[1])
            if m:
                stats[key] = float(m.group(1))

    # The last "Video stream is" line is the format the session actually used
    formats = re.findall(r"Video stream is \d+x\d+x\d+ \(format 0x([0-9a-fA-F]+)\)", text)
    codec = "?"
    if formats:
        fmt = int(formats[-1], 16)
        codec = "AV1" if fmt & 0xF000 else "HEVC" if fmt & 0x0F00 else "H.264" if fmt & 0x000F else "?"

    error = ""
    if not stats:
        errs = [l for l in text.splitlines() if re.search(r"SDL Error|Qt Critical|failed to start", l)]
        error = (errs[-1].split(" - ", 1)[-1] if errs else
                 "stream ended early" if ended_early else "no stats logged")
    return Result(case, stats, codec, error)


def format_table(results: list[Result]) -> str:
    cols = [("case", 36), ("codec", 6), ("host", 6), ("net", 7), ("decode", 7),
            ("render", 7), ("total", 7), ("jitter%", 8), ("fps", 6)]
    lines = ["".join(name.ljust(w) for name, w in cols)]
    for r in results:
        s = r.stats
        if r.error:
            lines.append(r.case.name.ljust(36) + "  -- " + r.error)
            continue
        total = r.total_ms
        row = [
            r.case.name, r.codec,
            f"{s.get('host_ms', 0):.1f}",
            f"{s.get('net_ms', 0):.0f}±{s.get('net_var_ms', 0):.0f}",
            f"{s.get('decode_ms', 0):.2f}",
            f"{s.get('render_ms', 0):.2f}",
            f"{total:.1f}" if total is not None else "?",
            f"{s.get('jitter_drop_pct', 0) + s.get('net_drop_pct', 0):.2f}",
            f"{s.get('net_fps', 0):.0f}",
        ]
        lines.append("".join(v.ljust(w) for v, (_, w) in zip(row, cols)))
    lines.append("times in ms; total = host + network + decode + queue + render "
                 "(excludes capture/scanout)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("--app", default="Desktop")
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--resolution", default="1920x1080")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--only", help="comma-separated groups: base,codec,bitrate,resolution,fps")
    ap.add_argument("--bin", default="")
    opts = ap.parse_args()

    binary = resolve_moonlight_bin(opts.bin)
    cases = default_cases(opts.resolution, opts.fps)
    if opts.only:
        groups = set(opts.only.split(","))
        cases = [c for c in cases if c.group in groups]

    w, h = (int(v) for v in opts.resolution.split("x"))
    results = []
    with HeadlessCompositor(w, h) as comp:
        for case in cases:
            print(f"running: {case.name} ({opts.seconds}s)...", flush=True)
            results.append(run_case(binary, opts.host, opts.app, case, opts.seconds, comp))
    print()
    print(format_table(results))


if __name__ == "__main__":
    main()
