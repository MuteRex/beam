"""Automatic provider: every route at once, one card per machine.

Runs local discovery and Tailscale together, identifies each Sunshine host by
its unique id, and merges a machine seen both ways into a single Host whose
`extra["routes"]` lists every way to reach it. The launcher then connects over
the fastest route (LAN first).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .. import probe
from .base import DiscoveryProvider, Host
from .local import LocalProvider
from .tailscale import TailscaleProvider


class AutoProvider(DiscoveryProvider):
    id = "auto"
    label = "Automatic"
    empty_message = "No hosts found on this network or your tailnet."

    def __init__(self) -> None:
        self.local = LocalProvider()
        self.tailscale = TailscaleProvider()

    def readiness_error(self):
        # Usable as long as at least one route works
        errors = [p.readiness_error() for p in (self.local, self.tailscale)]
        if all(errors):
            return " ".join(errors)
        return None

    def direct_address(self, host: Host) -> str:
        return self.tailscale.direct_address(host)

    def list_hosts(self) -> list[Host]:
        with ThreadPoolExecutor(max_workers=2) as ex:
            local_f = ex.submit(self._safe, self.local)
            ts_f = ex.submit(self._tailscale_hosts)
            local_hosts, ts_hosts = local_f.result(), ts_f.result()

        by_uid = {h.extra["uniqueid"]: h for h in local_hosts if h.extra.get("uniqueid")}
        merged = list(local_hosts)
        for t in ts_hosts:
            uid = t.extra.get("uniqueid")
            local = by_uid.get(uid) if uid else None
            if local is None:
                merged.append(t)
                continue
            # Same machine on both: keep the local card, add the tailnet route
            local.extra["routes"] += t.extra["routes"]
            local.extra["ts_path"] = t.extra.get("ts_path", "")
            local.os = local.os or t.os
            local.detail = "Online"

        merged.sort(key=lambda h: (not h.online, not h.extra.get("hostable"), h.name.lower()))
        return merged

    @staticmethod
    def _safe(provider) -> list[Host]:
        try:
            if provider.readiness_error():
                return []
            return provider.list_hosts()
        except Exception:  # noqa: BLE001 - one route failing must not hide the other
            return []

    def _tailscale_hosts(self) -> list[Host]:
        hosts = self._safe(self.tailscale)
        probe.mark_hostable(hosts)

        def identify(h):
            ident = probe.server_identity(h.address) if h.extra.get("hostable") else None
            return h, ident

        with ThreadPoolExecutor(max_workers=8) as ex:
            for h, ident in ex.map(identify, hosts):
                if ident:
                    h.extra["uniqueid"] = ident[0]
        probe.mark_direct(self.tailscale, hosts)
        return hosts
