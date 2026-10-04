"""Connection diagnostics behind "Test connection…": ping, the host's encoder
capabilities, and a short headless stream measured with the current settings.
Each number is compared with what a healthy LAN setup should show.
"""
from __future__ import annotations

import re
import subprocess
import urllib.request
from dataclasses import dataclass, field

from . import bench

# Bits of Sunshine's ServerCodecModeSupport
SCM_H264 = 0x00001
SCM_HEVC = 0x00100
SCM_AV1 = 0x10000 | 0x20000

GOOD, OK, BAD = "good", "ok", "bad"


@dataclass
class Metric:
    label: str
    value: str
    rating: str
    target: str


@dataclass
class Report:
    address: str
    metrics: list[Metric] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    error: str = ""
    total_ms: float | None = None


def _ping(address: str) -> tuple[float, float, float] | None:
    """(avg ms, jitter ms, loss %) over 20 quick pings."""
    try:
        out = subprocess.run(["ping", "-c", "20", "-i", "0.2", "-q", address],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    loss = re.search(r"([\d.]+)% packet loss", out)
    rtt = re.search(r"= [\d.]+/([\d.]+)/[\d.]+/([\d.]+) ms", out)
    if not loss or not rtt:
        return None
    return float(rtt.group(1)), float(rtt.group(2)), float(loss.group(1))


def _host_codecs(address: str) -> set[str] | None:
    try:
        with urllib.request.urlopen(f"http://{address}:47989/serverinfo", timeout=4) as r:
            xml = r.read(65536).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    m = re.search(r"<ServerCodecModeSupport>(\d+)<", xml)
    if not m:
        return None
    mask = int(m.group(1))
    codecs = set()
    if mask & SCM_H264:
        codecs.add("H.264")
    if mask & SCM_HEVC:
        codecs.add("HEVC")
    if mask & SCM_AV1:
        codecs.add("AV1")
    return codecs


def _rate(value: float, good: float, ok: float) -> str:
    return GOOD if value <= good else OK if value <= ok else BAD


def run(launcher, address: str, app: str = "Desktop", seconds: int = 15,
        progress=lambda msg: None) -> Report:
    report = Report(address)
    cfg = launcher.config

    progress("Pinging host…")
    ping = _ping(address)
    if ping:
        avg, jitter, loss = ping
        report.metrics.append(Metric("Ping", f"{avg:.1f} ms ±{jitter:.1f}",
                                     _rate(avg, 1.5, 5), "≤1.5 ms wired, ≤5 ms Wi-Fi"))
        if loss > 0:
            report.metrics.append(Metric("Packet loss", f"{loss:.0f}%", BAD, "0%"))
        if avg > 1.5:
            report.advice.append(
                "Network round trip is Wi-Fi-like. Ethernet on the host (or both "
                "machines on 5 GHz/6 GHz, same band) typically saves 1–4 ms and "
                "removes jitter spikes.")

    progress("Checking host encoder…")
    codecs = _host_codecs(address)
    if codecs is not None:
        hw = "HEVC" in codecs or "AV1" in codecs
        report.metrics.append(Metric("Host codecs", ", ".join(sorted(codecs)) or "none",
                                     GOOD if hw else BAD, "H.264 + HEVC (+ AV1)"))

    progress(f"Streaming for {seconds}s (headless)…")
    case = bench.Case("current settings", launcher.video_args())
    try:
        with bench.HeadlessCompositor(*_resolution(cfg)) as comp:
            result = bench.run_case(launcher.bin, address, app, case, seconds, comp)
    except RuntimeError as e:
        report.error = str(e)
        return report

    if result.error:
        report.error = f"Test stream failed: {result.error}"
        return report

    s = result.stats
    fps_target = float(cfg.get("fps") or 60)
    host_ms = s.get("host_ms", 0)
    report.metrics += [
        Metric("Codec used", result.codec, GOOD, ""),
        Metric("Host encode", f"{host_ms:.1f} ms (max {s.get('host_max_ms', 0):.0f})",
               _rate(host_ms, 6, 10), "≤6 ms with a GPU encoder"),
        Metric("Network", f"{s.get('net_ms', 0):.0f} ms ±{s.get('net_var_ms', 0):.0f}",
               _rate(s.get("net_ms", 0), 2, 5), "≤2 ms wired, ≤5 ms Wi-Fi"),
        Metric("Decode", f"{s.get('decode_ms', 0):.2f} ms",
               _rate(s.get("decode_ms", 0), 3, 8), "≤3 ms hardware decode"),
        Metric("Render", f"{s.get('render_ms', 0) + s.get('queue_ms', 0):.2f} ms",
               _rate(s.get("render_ms", 0), 3, 8), "≤3 ms with V-Sync off"),
        Metric("Dropped frames",
               f"{s.get('net_drop_pct', 0) + s.get('jitter_drop_pct', 0):.2f}%",
               _rate(s.get("net_drop_pct", 0) + s.get("jitter_drop_pct", 0), 0.5, 2), "<0.5%"),
        Metric("Frame rate", f"{s.get('net_fps', 0):.0f} / {fps_target:.0f} fps",
               GOOD if s.get("net_fps", 0) >= fps_target * 0.95 else BAD, "matches setting"),
    ]
    report.total_ms = result.total_ms
    if report.total_ms is not None:
        report.metrics.append(Metric("Total (est.)", f"{report.total_ms:.1f} ms",
                                     _rate(report.total_ms, 12, 20), "8–12 ms on a good LAN"))

    if host_ms > 10 and codecs is not None and "HEVC" not in codecs:
        report.advice.insert(0,
            "The host is encoding on its CPU (it only offers H.264). Getting "
            "Sunshine onto the GPU encoder (VAAPI/NVENC/AMF) is the biggest win: "
            "encode drops to a few ms and HEVC/AV1 become available.")
    elif host_ms > 10:
        report.advice.insert(0,
            "Host encoding is slow. Lower the resolution or check that the host "
            "isn't on battery/power-saving or thermally throttling.")
    if s.get("net_fps", 0) < fps_target * 0.95:
        report.advice.append(
            f"The host only delivered {s.get('net_fps', 0):.0f} fps of the "
            f"{fps_target:.0f} requested, so it can't keep up at these settings.")
    if s.get("decode_ms", 0) > 8:
        report.advice.append("Decoding is slow; set Video decoder to “hardware”.")
    if cfg.get("vsync") or cfg.get("frame_pacing"):
        report.advice.append("V-Sync/frame pacing are on; turning them off saves up to a frame.")
    if not report.advice:
        report.advice.append("Everything is within the normal range for a LAN stream.")
    return report


def _resolution(cfg) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in (cfg.get("resolution") or "1920x1080").split("x"))
        return w, h
    except ValueError:
        return 1920, 1080
