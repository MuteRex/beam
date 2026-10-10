"""Bitrate settings shared by Settings, the launcher and Test connection.
Values are kbps; 0 = Moonlight auto / no cap."""
from __future__ import annotations

# Denser at the low end, where mobile and Wi-Fi links sit
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


def _cap(kbps: int, limit: int) -> int:
    """`kbps` no higher than `limit` (0 = no limit); 0 (auto) becomes the limit."""
    if limit <= 0:
        return kbps
    return min(kbps, limit) if kbps else limit


def choose(config: dict, route: str, host_key: str | None = None,
           metered: bool = False) -> int:
    """Per-computer value from Test connection, else Home bitrate, capped at
    Away bitrate off the LAN (Moonlight can't lower its bitrate mid-stream).
    On a metered connection (a phone hotspot) the Away bitrate caps every
    stream, tested values included."""
    away = int(config.get("away_bitrate") or 0)
    tested = host_limit(config, host_key, route)
    if tested:
        kbps = min(tested, MAX_KBPS)
    else:
        home = int(config.get("bitrate") or 0)
        kbps = home if route == HOME else _cap(home, away)
    return _cap(kbps, away) if metered else kbps
