"""Tailscale discovery provider.

Reads `tailscale status --json` and turns every peer into a Host. This is the
working provider: it gives us 'machines appear in a list, reachable from
anywhere, no port-forwarding' for free, which is the Parsec-like feel.
"""
from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

from .base import DiscoveryProvider, Host


def _ago(iso: str) -> str:
    """Human 'last seen' from a tailscale RFC3339 timestamp."""
    if not iso or iso.startswith("0001"):
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    secs = (datetime.now(timezone.utc) - t).total_seconds()
    if secs < 90:
        return "just now"
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= n:
            return f"last seen {int(secs // n)}{unit} ago"
    return "just now"


class TailscaleProvider(DiscoveryProvider):
    id = "tailscale"
    label = "Tailscale"
    empty_message = "No other devices on your tailnet."

    def __init__(self) -> None:
        self._bin = shutil.which("tailscale") or "/usr/bin/tailscale"

    def readiness_error(self):
        if not shutil.which(self._bin) and not self._bin.startswith("/"):
            return "Tailscale is not installed."
        try:
            self._status()
        except FileNotFoundError:
            return "Tailscale is not installed."
        except RuntimeError as e:
            return str(e)
        return None

    def _status(self) -> dict:
        try:
            out = subprocess.run(
                [self._bin, "status", "--json"],
                capture_output=True, text=True, timeout=8,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Tailscale did not respond.")
        if out.returncode != 0:
            msg = (out.stderr or out.stdout).strip() or "tailscale status failed"
            if "Logged out" in msg or "NeedsLogin" in msg:
                raise RuntimeError("Tailscale is logged out. Run: tailscale up")
            raise RuntimeError(msg.splitlines()[0])
        return json.loads(out.stdout)

    def list_hosts(self) -> list[Host]:
        data = self._status()
        self_id = (data.get("Self") or {}).get("ID")
        hosts: list[Host] = []
        for peer in (data.get("Peer") or {}).values():
            if peer.get("ID") == self_id:
                continue
            ips = peer.get("TailscaleIPs") or []
            addr = ips[0] if ips else (peer.get("DNSName") or "").rstrip(".")
            if not addr:
                continue
            online = bool(peer.get("Online"))
            hostname = peer.get("HostName") or ""
            dns_label = (peer.get("DNSName") or "").split(".")[0]
            if hostname.lower() in ("", "localhost"):
                hostname = dns_label or addr
            hosts.append(Host(
                id=peer.get("PublicKey") or peer.get("ID") or addr,
                name=hostname,
                address=addr,
                os=(peer.get("OS") or "").lower(),
                online=online,
                detail="Online" if online else _ago(peer.get("LastSeen", "")),
                provider=self.id,
                extra={"dns": (peer.get("DNSName") or "").rstrip("."),
                       "routes": [{"kind": "tailscale", "address": addr}]},
            ))
        # Online first, then alphabetical.
        hosts.sort(key=lambda h: (not h.online, h.name.lower()))
        return hosts

    def direct_address(self, host: Host) -> str:
        """The peer's LAN IP when Tailscale reaches it directly over a private
        network ("pong ... via 192.168.x.y:41641"); "" if relayed or unknown."""
        try:
            out = subprocess.run(
                [self._bin, "ping", "-c", "1", "--timeout", "2s", host.address],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if re.search(r"via DERP\(", out.stdout):
            host.extra["ts_path"] = "relay"
            return ""
        m = re.search(r"via \[?([0-9a-fA-F.:]+?)\]?:\d+ in", out.stdout)
        if not m:
            return ""
        host.extra["ts_path"] = "direct"
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            return ""
        return str(ip) if ip.is_private and not ip.is_loopback else ""
