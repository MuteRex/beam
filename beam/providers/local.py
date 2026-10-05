"""Local-network discovery provider.

Sunshine announces itself over mDNS as `_nvstream._tcp`. We ask the system's
Avahi daemon over D-Bus (no extra dependencies), then read each host's
serverinfo for its unique id and name. No account, no Tailscale, works offline,
and it is always the shortest path.
"""
from __future__ import annotations

import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Gio, GLib

from .. import probe
from .base import DiscoveryProvider, Host

AVAHI = "org.freedesktop.Avahi"
IF_UNSPEC = -1
PROTO_UNSPEC = -1
PROTO_INET = 0
SERVICE_TYPE = "_nvstream._tcp"


def browse(timeout: float = 2.0) -> list[tuple[str, str, int]]:
    """[(service name, IPv4 address, port)] for every Sunshine/GameStream host
    Avahi knows about. Blocks up to `timeout`; call off the main thread."""
    ctx = GLib.MainContext.new()
    ctx.push_thread_default()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        path = bus.call_sync(
            AVAHI, "/", "org.freedesktop.Avahi.Server2", "ServiceBrowserPrepare",
            GLib.Variant("(iissu)", (IF_UNSPEC, PROTO_INET, SERVICE_TYPE, "local", 0)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]

        items, done = [], [False]

        def on_signal(_conn, _sender, _path, _iface, member, params):
            if member == "ItemNew":
                items.append(params.unpack())
            elif member in ("AllForNow", "Failure"):
                done[0] = True

        sub = bus.signal_subscribe(AVAHI, "org.freedesktop.Avahi.ServiceBrowser", None,
                                   path, None, Gio.DBusSignalFlags.NONE, on_signal)
        try:
            bus.call_sync(AVAHI, path, "org.freedesktop.Avahi.ServiceBrowser", "Start",
                          None, None, Gio.DBusCallFlags.NONE, 3000, None)
            deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
            while not done[0] and GLib.get_monotonic_time() < deadline:
                ctx.iteration(False) or GLib.usleep(20000)
        finally:
            bus.signal_unsubscribe(sub)
            try:
                bus.call_sync(AVAHI, path, "org.freedesktop.Avahi.ServiceBrowser", "Free",
                              None, None, Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass

        found, seen = [], _own_addresses()
        for iface, proto, name, stype, domain, _flags in items:
            try:
                r = bus.call_sync(
                    AVAHI, "/", "org.freedesktop.Avahi.Server", "ResolveService",
                    GLib.Variant("(iisssiu)", (iface, proto, name, stype, domain, PROTO_INET, 0)),
                    None, Gio.DBusCallFlags.NONE, 3000, None).unpack()
            except GLib.Error:
                continue
            address, port = r[7], r[8]
            # Anyone on the LAN can announce a service; only take a plain IP
            if probe.valid_address(address) and address not in seen:
                seen.add(address)
                found.append((name, address, port))
        return found
    finally:
        ctx.pop_thread_default()


def _own_addresses() -> set[str]:
    """This machine's IPv4 addresses, so we don't list ourselves."""
    own = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            own.add(info[4][0])
    except OSError:
        pass
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                own.add(parts[parts.index("inet") + 1].split("/")[0])
    except (OSError, subprocess.SubprocessError):
        pass
    return own


class LocalProvider(DiscoveryProvider):
    id = "local"
    label = "Local network"
    empty_message = "No Sunshine hosts found on this network."

    def readiness_error(self):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
            bus.call_sync(AVAHI, "/", "org.freedesktop.Avahi.Server", "GetVersionString",
                          None, None, Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            return "Local discovery needs the Avahi daemon (avahi-daemon)."
        return None

    def list_hosts(self) -> list[Host]:
        services = browse()

        def identify(svc):
            name, address, _port = svc
            return svc, probe.server_identity(address)

        hosts = []
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(services)))) as ex:
            for (name, address, _port), ident in ex.map(identify, services):
                uid, hostname = ident if ident else ("", "")
                hosts.append(Host(
                    id=f"sunshine:{uid}" if uid else f"mdns:{address}",
                    name=hostname or name,
                    address=address,
                    online=True,
                    detail="Online",
                    provider=self.id,
                    extra={"hostable": ident is not None, "uniqueid": uid,
                           "lan_address": address,
                           "routes": [{"kind": "lan", "address": address}]},
                ))
        hosts.sort(key=lambda h: h.name.lower())
        return hosts
