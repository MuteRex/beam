"""Decide which discovered devices are actually *connectable* hosts.

A Tailscale peer being online doesn't mean it can host a stream (your phone
can't). A machine running Sunshine/GameStream answers on its control port, so a
quick TCP connect tells us whether it's a real host.

Everything here talks to machines on the network, so their answers are
untrusted: addresses are validated before use and serverinfo reads are capped.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Sunshine / GameStream control ports. 47989 = HTTP serverinfo (always open when
# hosting), 47984 = HTTPS. One open is enough to call it a host.
HOST_PORTS = (47989, 47984)
SERVERINFO_PORT = 47989
SERVERINFO_MAX_BYTES = 65536

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})"
                       r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}))*\.?$")


def valid_address(address: str) -> bool:
    """An IP literal or DNS name, and nothing a command line could read as an
    option or a URL could read as anything but a host."""
    if not isinstance(address, str) or not address:
        return False
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(address))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


# serverinfo is a single plain GET; a host that redirects is not Sunshine
_opener = urllib.request.build_opener(_NoRedirect)


# Tailscale's IPv6 range is a ULA too, but it reaches peers over the internet
_TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")


def is_lan_address(address: str) -> bool:
    """True for addresses on the local network (private IPv4, link-local, IPv6
    ULA, *.local names). Tailscale addresses and public ones are "away": the
    stream crosses the internet, where bandwidth is lower and less steady."""
    if not isinstance(address, str) or not address:
        return False
    if address.rstrip(".").lower().endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False  # other names (MagicDNS, DNS) could be anywhere
    if ip in _TAILSCALE_V4 or ip in _TAILSCALE_V6:
        return False
    if ip.version == 6:
        return ip.is_link_local or ip in ipaddress.ip_network("fc00::/7")
    return ip.is_private and not ip.is_loopback or ip.is_link_local


def server_info(address: str, timeout: float = 1.5) -> dict[str, str] | None:
    """Sunshine's unauthenticated serverinfo as {tag: text}, or None."""
    if not valid_address(address):
        return None
    host = f"[{address}]" if ":" in address else address
    try:
        with _opener.open(f"http://{host}:{SERVERINFO_PORT}/serverinfo", timeout=timeout) as r:
            xml = r.read(SERVERINFO_MAX_BYTES).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"<(\w+)>([^<]*)</\1>", xml)}


def is_hostable(address: str, timeout: float = 0.7) -> bool:
    if not valid_address(address):
        return False
    for port in HOST_PORTS:
        try:
            with socket.create_connection((address, port), timeout):
                return True
        except OSError:
            continue
    return False


def server_identity(address: str, timeout: float = 1.5) -> tuple[str, str] | None:
    """(uniqueid, hostname) from serverinfo. The uniqueid identifies the same
    machine across LAN and Tailscale addresses. It is self-reported, so it only
    groups routes in the UI; Moonlight's pinned certificate is what actually
    proves which machine a stream connects to."""
    info = server_info(address, timeout)
    if not info or not info.get("uniqueid"):
        return None
    return info["uniqueid"], info.get("hostname", "")


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
