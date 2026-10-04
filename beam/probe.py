"""Decide which discovered devices are actually *connectable* hosts.

A Tailscale peer being online doesn't mean it can host a stream (your phone
can't). A machine running Sunshine/GameStream answers on its control port, so a
quick TCP connect tells us whether it's a real host.
"""
from __future__ import annotations

import socket
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


def mark_hostable(hosts, timeout: float = 0.7) -> None:
    """Set host.extra['hostable'] on each host, probing online ones in parallel.
    Offline hosts are never hostable."""
    online = [h for h in hosts if h.online]
    for h in hosts:
        if not h.online:
            h.extra["hostable"] = False
    if not online:
        return
    with ThreadPoolExecutor(max_workers=min(16, len(online))) as ex:
        results = ex.map(lambda h: (h, is_hostable(h.address, timeout)), online)
        for h, ok in results:
            h.extra["hostable"] = ok
