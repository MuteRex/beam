#!/usr/bin/env python3
"""Build the EDID for Beam's virtual high-refresh display.

A host whose own screen is 60 Hz can only give Sunshine 60 new frames a second.
Forcing an unused HDMI port "connected" with this EDID makes the GPU drive a
real 1080p display at up to 144 Hz with nothing plugged in, which Sunshine can
then capture.

Timings are CVT reduced-blanking v2 and kept under 340 MHz, so HDMI 2.0
scrambling (which needs a real sink to answer over SCDC) is never required.

    python3 make_edid.py out.bin            # 1080p 144/120/60
    python3 make_edid.py out.bin 2560x1440  # other resolution
"""
from __future__ import annotations

import math
import struct
import sys

MAX_TMDS_MHZ = 340  # HDMI 1.4 limit: no scrambling


def cvt_rb2(width: int, height: int, refresh: float) -> dict:
    """CVT reduced blanking v2 timing."""
    hblank, hfront, hsync = 80, 8, 32
    vsync, vback_min, min_vblank_us = 8, 6, 460.0
    frame_us = 1e6 / refresh
    vtotal = math.ceil(height / (1 - min_vblank_us / frame_us))
    vblank = max(vtotal - height, vsync + vback_min + 1)
    vtotal = height + vblank
    htotal = width + hblank
    clock_khz = round(htotal * vtotal * refresh / 10000) * 10  # EDID stores 10 kHz units
    return dict(width=width, height=height, refresh=refresh, clock_khz=clock_khz,
                hblank=hblank, hfront=hfront, hsync=hsync,
                vblank=vblank, vfront=vblank - vsync - vback_min, vsync=vsync)


def detailed_timing(t: dict) -> bytes:
    pclk = t["clock_khz"] // 10
    ha, hb, va, vb = t["width"], t["hblank"], t["height"], t["vblank"]
    hfp, hs, vfp, vs = t["hfront"], t["hsync"], t["vfront"], t["vsync"]
    width_mm, height_mm = 527, 296  # ~24" 16:9
    return struct.pack(
        "<H13B2B", pclk,
        ha & 0xFF, hb & 0xFF, ((ha >> 8) << 4) | (hb >> 8),
        va & 0xFF, vb & 0xFF, ((va >> 8) << 4) | (vb >> 8),
        hfp & 0xFF, hs & 0xFF, ((vfp & 0xF) << 4) | (vs & 0xF),
        ((hfp >> 8) << 6) | ((hs >> 8) << 4) | ((vfp >> 4) << 2) | (vs >> 4),
        width_mm & 0xFF, height_mm & 0xFF, ((width_mm >> 8) << 4) | (height_mm >> 8),
        0, 0) + bytes([0x1E])  # no borders; digital separate sync, +h +v


def text_descriptor(tag: int, text: str) -> bytes:
    body = text.encode("ascii")[:13]
    body = body + (b"\n" + b" " * 12)[: 13 - len(body)] if len(body) < 13 else body
    return bytes([0, 0, 0, tag, 0]) + body


def range_descriptor(min_v: int, max_v: int, min_h: int, max_h: int, max_mhz: int) -> bytes:
    return bytes([0, 0, 0, 0xFD, 0, min_v, max_v, min_h, max_h,
                  math.ceil(max_mhz / 10), 0x00, 0x0A]) + b" " * 6


def checksum(block: bytes) -> bytes:
    return block + bytes([(-sum(block)) & 0xFF])


def base_block(timings: list[dict]) -> bytes:
    header = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
    # Manufacturer "BEM" (compressed ASCII), product 0x0144, serial 1, week 40 / 2026
    mfg = ((ord("B") - 64) << 10) | ((ord("E") - 64) << 5) | (ord("M") - 64)
    ident = struct.pack(">H", mfg) + struct.pack("<HIBB", 0x0144, 1, 40, 2026 - 1990)
    version = bytes([1, 3])  # HDMI requires EDID 1.3
    # Digital input; 53x30 cm; gamma 2.2; RGB colour, sRGB default, preferred timing
    basic = bytes([0x80, 53, 30, 120, 0x0E])
    chroma = bytes([0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54])
    established = bytes([0x20, 0x00, 0x00])  # 640x480@60, required by CTA-861
    standard = b"\x01\x01" * 8
    descriptors = [detailed_timing(t) for t in timings[:2]]
    max_clock = max(t["clock_khz"] for t in timings) / 1000
    descriptors.append(range_descriptor(
        48, math.ceil(max(t["refresh"] for t in timings)), 30,
        math.ceil(max(t["clock_khz"] / (t["width"] + t["hblank"]) for t in timings)), max_clock))
    descriptors.append(text_descriptor(0xFC, "Beam Virtual"))
    block = header + ident + version + basic + chroma + established + standard + b"".join(descriptors)
    block += bytes([1])  # one extension block
    assert len(block) == 127
    return checksum(block)


def cta_block(timings: list[dict]) -> bytes:
    """CTA-861 extension: HDMI VSDB (so the driver allows >165 MHz TMDS) and
    the remaining timings as extra detailed descriptors."""
    max_clock = max(t["clock_khz"] for t in timings) / 1000
    tmds = MAX_TMDS_MHZ
    # HDMI VSDB: OUI 00-0C-03, phys addr 1.0.0.0, no deep colour, max TMDS / 5
    hdmi_vsdb_payload = bytes([0x03, 0x0C, 0x00, 0x10, 0x00, 0x00, tmds // 5])
    hdmi_vsdb = bytes([(3 << 5) | len(hdmi_vsdb_payload)]) + hdmi_vsdb_payload
    # Video data block: VIC 1 (640x480, required) and VIC 16 (1080p60). Neither is
    # flagged native, so the 144 Hz detailed timing stays the preferred mode.
    video = bytes([(2 << 5) | 2, 1, 16])
    # Video capability block: RGB quantization range is selectable
    vcdb = bytes([(7 << 5) | 2, 0x00, 0x4A])  # QS, IT+CE always underscanned
    data = video + vcdb + hdmi_vsdb
    dtds = b"".join(detailed_timing(t) for t in timings[2:])
    offset = 4 + len(data)
    # Underscanned IT content; one native DTD (the preferred timing in block 0)
    block = bytes([0x02, 0x03, offset, 0x81]) + data + dtds
    block += b"\x00" * (127 - len(block))
    return checksum(block)


def build(width: int = 1920, height: int = 1080, rates=(144, 120, 60)) -> bytes:
    timings = [cvt_rb2(width, height, r) for r in rates]
    too_fast = [t for t in timings if t["clock_khz"] / 1000 > MAX_TMDS_MHZ]
    if too_fast:
        raise SystemExit(f"{too_fast[0]['refresh']} Hz needs {too_fast[0]['clock_khz'] / 1000:.0f} MHz "
                         f"(> {MAX_TMDS_MHZ} MHz); use a lower refresh or resolution")
    return base_block(timings) + cta_block(timings)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "beam-virtual.bin"
    w, h = (int(v) for v in (sys.argv[2] if len(sys.argv) > 2 else "1920x1080").split("x"))
    with open(out, "wb") as f:
        f.write(build(w, h))
    print(out)
