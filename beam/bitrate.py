"""Bitrate choices shared by the Settings sliders, the launcher and the connection
test. Pure, so it is unit tested without a display.

All values are kbps, as Moonlight's --bitrate takes them; 0 means "no value"
(Moonlight's automatic choice, or no cap).
"""
from __future__ import annotations

# Slider stops: dense where it matters (mobile data, Wi-Fi), sparse above
STEPS_KBPS = [0, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000, 20000,
              25000, 30000, 40000, 50000, 60000, 80000, 100000, 120000, 150000]
MAX_KBPS = STEPS_KBPS[-1]

HOME, AWAY = "home", "away"


def index_for(kbps: int) -> int:
    """Slider position closest to `kbps` (0 = the zero stop)."""
    if not kbps or kbps <= 0:
        return 0
    return min(range(1, len(STEPS_KBPS)), key=lambda i: (abs(STEPS_KBPS[i] - kbps), i))


def kbps_at(index: int) -> int:
    return STEPS_KBPS[max(0, min(len(STEPS_KBPS) - 1, int(index)))]


def label(kbps: int, zero: str = "Auto") -> str:
    if not kbps or kbps <= 0:
        return zero
    mbps = kbps / 1000
    return f"{mbps:.0f} Mbps" if mbps == int(mbps) else f"{mbps:.1f} Mbps"


def gb_per_hour(kbps: int) -> float:
    """Data a stream at `kbps` uses in an hour (1 GB = 10^9 bytes)."""
    return max(0, kbps) * 1000 / 8 * 3600 / 1e9


def usage_hint(kbps: int) -> str:
    if not kbps or kbps <= 0:
        return ""
    gb = gb_per_hour(kbps)
    return f"about {gb:.1f} GB an hour" if gb < 10 else f"about {gb:.0f} GB an hour"


def route_of(is_lan: bool) -> str:
    return HOME if is_lan else AWAY


def host_limit(config: dict, host_key: str | None, route: str) -> int:
    """Per-computer bitrate saved from a connection test, 0 if none."""
    if not host_key:
        return 0
    entry = (config.get("host_bitrates") or {}).get(host_key) or {}
    value = entry.get(route, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def choose(config: dict, route: str, host_key: str | None = None) -> int:
    """The bitrate to stream at (0 = Moonlight auto).

    A per-computer value from Test connection wins: it was measured on this
    route. Otherwise home uses the Home bitrate, and away uses the Home bitrate
    capped at Away bitrate, since an internet link (a phone hotspot, say) is
    slower and less steady, and Moonlight can't lower its bitrate mid-stream.
    """
    tested = host_limit(config, host_key, route)
    if tested:
        return min(tested, MAX_KBPS)
    home = int(config.get("bitrate") or 0)
    if route == HOME:
        return home
    away = int(config.get("away_bitrate") or 0)
    if away <= 0:
        return home
    return min(home, away) if home else away
