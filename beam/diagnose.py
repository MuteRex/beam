"""Test connection: ping, host encoders, then headless streams at rising
bitrates until frames drop. Sunshine pads frames to the bitrate even on a
still desktop, so each step really loads the link."""
from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from . import bench, bitrate, options, probe
from .launcher import DESKTOP_APP

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


# kbps; a phone hotspot often can't hold more than 10-20 Mbps
HOME_LADDER = [10000, 20000, 35000, 50000, 80000]
AWAY_LADDER = [3000, 6000, 10000, 15000, 25000]

STEP_STARTUP_S = 3.0

PING_SHARE, CODEC_SHARE = 0.10, 0.02
LADDER_START = PING_SHARE + CODEC_SHARE


@dataclass
class Step:
    kbps: int
    rating: str = ""            # GOOD / OK / BAD once measured, "" while running
    drop_pct: float | None = None
    net_ms: float | None = None
    error: str = ""


@dataclass
class Progress:
    fraction: float             # 0..1 for the whole test
    stage: str
    steps: list[Step]
    current: int | None = None  # index of the step being streamed


@dataclass
class Report:
    address: str
    route: str = bitrate.HOME
    metrics: list[Metric] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    error: str = ""
    total_ms: float | None = None
    steps: list[Step] = field(default_factory=list)
    recommended_kbps: int | None = None
    ping_ms: float | None = None
    jitter_ms: float | None = None
    loss_pct: float | None = None
    verdict: str = ""
    verdict_rating: str = ""


def ladder_for(route: str) -> list[int]:
    return list(HOME_LADDER if route == bitrate.HOME else AWAY_LADDER)


def estimate(route: str, step_seconds: int) -> tuple[int, float]:
    """(seconds, worst-case MB) if every ladder step runs."""
    rungs = ladder_for(route)
    seconds = 5 + len(rungs) * (step_seconds + STEP_STARTUP_S + 1)
    mb = sum(rungs) * 1000 / 8 * (step_seconds + STEP_STARTUP_S) / 1e6
    return int(round(seconds)), mb


def rate_step(stats: dict, error: str = "") -> str:
    """Clean (GOOD) at <=1% frames dropped by the network, usable (OK) to 3%."""
    if error or not stats:
        return BAD
    dropped = stats.get("net_drop_pct", 0) + stats.get("jitter_drop_pct", 0)
    return GOOD if dropped <= 1 else OK if dropped <= 3 else BAD


def recommend(steps: list[Step]) -> int | None:
    """85% of the highest clean step in whole Mbps, or the top step if every
    step was clean. None if nothing was usable."""
    measured = [s for s in steps if s.rating]
    clean = [s.kbps for s in measured if s.rating == GOOD]
    if clean:
        best = max(clean)
        if best == max(s.kbps for s in measured) and all(s.rating == GOOD for s in measured) \
                and len(measured) == len(steps):
            return best
        return max(1000, int(best * 0.85) // 1000 * 1000)
    usable = [s.kbps for s in measured if s.rating == OK]
    if usable:
        return max(1000, int(max(usable) * 0.6) // 1000 * 1000)
    return None


def verdict(recommended: int | None, ping_ms: float | None, loss_pct: float | None,
            route: str) -> tuple[str, str]:

    if recommended is None:
        return "Poor", BAD
    lossy = (loss_pct or 0) > 2
    slow = ping_ms is not None and ping_ms > (15 if route == bitrate.HOME else 80)
    if recommended >= (35000 if route == bitrate.HOME else 15000) and not lossy and not slow:
        return "Excellent", GOOD
    if recommended >= (15000 if route == bitrate.HOME else 6000) and not lossy:
        return "Good", GOOD
    if recommended >= 3000:
        return "Usable", OK
    return "Poor", BAD


def _with_bitrate(args: list[str], kbps: int) -> list[str]:

    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--bitrate":
            skip = True
            continue
        out.append(a)
    return out + ["--bitrate", str(kbps)]


def _ping(address: str) -> tuple[float, float, float] | None:
    """(avg ms, jitter ms, loss %) over 20 quick pings."""
    if not probe.valid_address(address):
        return None
    try:
        out = subprocess.run(["ping", "-c", "20", "-i", "0.2", "-q", "--", address],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    loss = re.search(r"([\d.]+)% packet loss", out)
    rtt = re.search(r"= [\d.]+/([\d.]+)/[\d.]+/([\d.]+) ms", out)
    if not loss or not rtt:
        return None
    return float(rtt.group(1)), float(rtt.group(2)), float(loss.group(1))


def _host_codecs(address: str) -> set[str] | None:
    info = probe.server_info(address, timeout=4)
    mask = (info or {}).get("ServerCodecModeSupport", "")
    if not mask.isdigit():
        return None
    mask = int(mask)
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


def run(launcher, address: str, app: str = "Desktop", step_seconds: int = 5,
        progress=lambda p: None, stop: threading.Event | None = None) -> Report:
    """`stop` ends the test after the current step."""
    route = bitrate.route_of(probe.is_lan_address(address))
    report = Report(address, route)
    report.steps = [Step(kbps) for kbps in ladder_for(route)]
    cfg = launcher.config
    stop = stop or threading.Event()

    shown = [0.0]
    lock = threading.Lock()

    def tell(fraction, stage, current=None):
        # The ticker thread and the step loop both report
        with lock:
            shown[0] = max(shown[0], min(1.0, round(fraction, 4)))
            progress(Progress(shown[0], stage, [Step(**vars(s)) for s in report.steps], current))

    tell(0.0, "Measuring latency…")
    ping = _ping(address)
    if ping:
        avg, jitter, loss = ping
        report.ping_ms, report.jitter_ms, report.loss_pct = avg, jitter, loss
        home = route == bitrate.HOME
        report.metrics.append(Metric("Ping", f"{avg:.1f} ms ±{jitter:.1f}",
                                     _rate(avg, 1.5, 5) if home else _rate(avg, 30, 80),
                                     "≤1.5 ms wired, ≤5 ms Wi-Fi" if home else "≤30 ms is great over the internet"))
        if loss > 0:
            report.metrics.append(Metric("Packet loss", f"{loss:.0f}%", BAD, "0%"))
        if home and avg > 1.5:
            report.advice.append(
                "Network round trip is Wi-Fi-like. Ethernet on the host (or both "
                "machines on 5 GHz/6 GHz, same band) typically saves 1–4 ms and "
                "removes jitter spikes.")

    tell(PING_SHARE, "Checking the host’s encoder…")
    codecs = _host_codecs(address)
    if codecs is not None:
        hw = "HEVC" in codecs or "AV1" in codecs
        report.metrics.append(Metric("Host codecs", ", ".join(sorted(codecs)) or "none",
                                     GOOD if hw else BAD, "H.264 + HEVC (+ AV1)"))

    # No --quit-after: the host app must survive between steps
    flags = [a for a in options.cli_args(cfg) if a not in ("--quit-after",)]
    base = launcher.video_args() + flags
    per_step = (1.0 - LADDER_START) / len(report.steps)
    best = None
    try:
        with bench.HeadlessCompositor(*options.resolution_size(cfg)) as comp:
            for i, step in enumerate(report.steps):
                if stop.is_set():
                    break
                start = LADDER_START + i * per_step
                stage = f"Streaming at {bitrate.label(step.kbps)}…"
                tell(start, stage, i)

                done = threading.Event()
                expected = step_seconds + STEP_STARTUP_S

                def ticker(t0=time.monotonic(), start=start, stage=stage, i=i):
                    while not done.wait(0.25):
                        tell(start + per_step * min(0.95, (time.monotonic() - t0) / expected), stage, i)
                threading.Thread(target=ticker, daemon=True).start()

                case = bench.Case(f"{step.kbps} kbps", _with_bitrate(base, step.kbps))
                try:
                    result = bench.run_case(launcher.bin, address, app, case,
                                            int(step_seconds + STEP_STARTUP_S), comp)
                finally:
                    done.set()

                step.error = result.error
                step.rating = rate_step(result.stats, result.error)
                if result.stats:
                    step.drop_pct = result.stats.get("net_drop_pct", 0) + result.stats.get("jitter_drop_pct", 0)
                    step.net_ms = result.stats.get("net_ms")
                if step.rating != BAD:
                    best = result
                tell(start + per_step, stage, i)
                if step.rating == BAD:
                    break
    except RuntimeError as e:
        report.error = str(e)
        return report
    finally:
        # The test's own Desktop session would otherwise keep running on the
        # host (and keep it on its streaming display). Games are left alone.
        if app == DESKTOP_APP and launcher.host_busy(address):
            launcher.end_session(address)

    report.recommended_kbps = recommend(report.steps)
    report.verdict, report.verdict_rating = verdict(report.recommended_kbps, report.ping_ms,
                                                    report.loss_pct, route)
    tell(1.0, "Done")

    first = report.steps[0]
    if best is None:
        report.error = (f"Test stream failed: {first.error}" if first.error and first.drop_pct is None
                        else "Even the lowest bitrate lost frames. The connection is too "
                             "unsteady to stream right now.")
        return report

    _add_timings(report, best, cfg, codecs)
    return report


def _add_timings(report: Report, result, cfg: dict, codecs: set[str] | None) -> None:
    s = result.stats
    home = report.route == bitrate.HOME
    fps_target = float(options.effective_fps(cfg))
    host_ms = s.get("host_ms", 0)
    report.metrics += [
        Metric("Codec used", result.codec, GOOD, ""),
        Metric("Host encode", f"{host_ms:.1f} ms (max {s.get('host_max_ms', 0):.0f})",
               _rate(host_ms, 6, 10), "≤6 ms with a GPU encoder"),
        Metric("Network", f"{s.get('net_ms', 0):.0f} ms ±{s.get('net_var_ms', 0):.0f}",
               _rate(s.get("net_ms", 0), 2, 5) if home else _rate(s.get("net_ms", 0), 30, 80),
               "≤2 ms wired, ≤5 ms Wi-Fi" if home else "≤30 ms is great over the internet"),
        Metric("Decode", f"{s.get('decode_ms', 0):.2f} ms",
               _rate(s.get("decode_ms", 0), 3, 8), "≤3 ms hardware decode"),
        Metric("Render", f"{s.get('render_ms', 0) + s.get('queue_ms', 0):.2f} ms",
               _rate(s.get("render_ms", 0), 3, 8), "≤3 ms with V-Sync off"),
        Metric("Frame rate", f"{s.get('net_fps', 0):.0f} / {fps_target:.0f} fps",
               GOOD if s.get("net_fps", 0) >= fps_target * 0.95 else BAD, "matches setting"),
    ]
    report.total_ms = result.total_ms
    if report.total_ms is not None:
        report.metrics.append(Metric("Total (est.)", f"{report.total_ms:.1f} ms",
                                     _rate(report.total_ms, 12, 20) if home else _rate(report.total_ms, 45, 90),
                                     "8–12 ms on a good LAN" if home else "≤45 ms feels local"))

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
    rec = report.recommended_kbps
    if rec and any(st.rating == BAD for st in report.steps):
        report.advice.insert(0,
            f"Frames started dropping above {bitrate.label(max(st.kbps for st in report.steps if st.rating == GOOD) if any(st.rating == GOOD for st in report.steps) else rec)}. "
            f"Streaming at {bitrate.label(rec)} leaves headroom for dips.")
    if not report.advice:
        report.advice.append("Everything is within the normal range."
                             if home else "Everything is within the normal range for an internet stream.")
