"""Decide which discovered devices are actually *connectable* hosts.

A Tailscale peer being online doesn't mean it can host a stream (your phone
can't). A machine running Sunshine/GameStream answers on its control port, so a
quick TCP connect tells us whether it's a real host.
"""
from __future__ import annotations

import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Sunshine / GameStream control ports. 47989 = HTTP serverinfo (always open when
# hosting), 47984 = HTTPS. One open is enough to call it a host.
HOST_PORTS = (47989, 47984)


def is_hostable(address: str, timeout: float = 0.7) -> bool:
    for port in HOST_PORTS:
        try:
            with socket.create_connection((address, port), timeout):
                return True
        except OSError:
            continue
    return False


def server_identity(address: str, timeout: float = 1.5) -> tuple[str, str] | None:
    """(uniqueid, hostname) from Sunshine's unauthenticated serverinfo. The
    uniqueid identifies the same machine across LAN and Tailscale addresses."""
    host = f"[{address}]" if ":" in address else address
    try:
        with urllib.request.urlopen(f"http://{host}:47989/serverinfo", timeout=timeout) as r:
            xml = r.read(65536).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    uid = re.search(r"<uniqueid>([^<]+)<", xml)
    name = re.search(r"<hostname>([^<]*)<", xml)
    if not uid:
        return None
    return uid.group(1).strip(), (name.group(1).strip() if name else "")


def mark_direct(provider, hosts, timeout: float = 0.7) -> None:
    """Set host.extra['lan_address'] for hosts the provider can reach more
    directly, but only if Sunshine actually answers on that address."""
    hostable = [h for h in hosts if h.extra.get("hostable") and "lan_address" not in h.extra]
    if not hostable:
        return

    def check(h):
        lan = provider.direct_address(h)
        return h, lan if lan and is_hostable(lan, timeout) else ""

    with ThreadPoolExecutor(max_workers=min(8, len(hostable))) as ex:
        for h, lan in ex.map(check, hostable):
            h.extra["lan_address"] = lan


def mark_hostable(hosts, timeout: float = 0.7) -> None:
    """Set host.extra['hostable'] on each host, probing online ones in parallel.
    Offline hosts are never hostable."""
    online = [h for h in hosts if h.online and "hostable" not in h.extra]
    for h in hosts:
        if not h.online:
            h.extra["hostable"] = False
    if not online:
        return
    with ThreadPoolExecutor(max_workers=min(16, len(online))) as ex:
        results = ex.map(lambda h: (h, is_hostable(h.address, timeout)), online)
        for h, ok in results:
            h.extra["hostable"] = ok
