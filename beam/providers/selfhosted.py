"""Self-hosted signaling provider — PLACEHOLDER.

This is the slot for the real 'works without Tailscale' path: a small signaling
+ relay service you host, that both ends check in with so they can discover each
other and punch through NAT the way Parsec's servers do. It is intentionally not
built yet — the class exists so the UI, the provider registry, and the config
already have a place for it. When built, fill in `list_hosts()` (and flip
`available` to True) and nothing else in the app needs to change.

Design notes for later (kept here so the plan lives with the code):
  * A tiny server (VPS or the always-on PC) holds a roster of registered
    machines keyed to your account, plus their current reachability candidates.
  * Host side registers + publishes ICE candidates; client side fetches the
    roster -> that becomes list_hosts(); on connect, exchange candidates and
    hand Moonlight a reachable address (direct hole-punched, or relayed).
  * Reuses the exact Host dataclass below, so the UI is already compatible.
"""
from __future__ import annotations

from .base import DiscoveryProvider, Host


class SelfHostedProvider(DiscoveryProvider):
    id = "selfhosted"
    label = "Self-hosted (coming soon)"
    available = False
    unavailable_message = (
        "The self-hosted connection service isn’t built yet.\n"
        "This is the planned way to connect without Tailscale — your own "
        "signaling + relay server. For now, use the Tailscale provider."
    )
    empty_message = unavailable_message

    def list_hosts(self) -> list[Host]:  # pragma: no cover - not built
        return []

    def readiness_error(self):
        return self.unavailable_message
