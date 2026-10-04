"""Discovery-provider contract.

A provider's only job is to answer "which hosts can I connect to right now?".
Everything above this layer (the UI, the launcher) is provider-agnostic, so a
new way of finding/reaching hosts — e.g. a self-hosted signaling + relay
server to replace Tailscale — is a new subclass and nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Host:
    """A machine we could stream from."""
    id: str                       # stable unique id (provider-specific)
    name: str                     # display name
    address: str                  # what Moonlight connects to (IP or DNS name)
    os: str = ""                  # "linux" / "windows" / "macos" / ...
    online: bool = False
    detail: str = ""              # short status line, e.g. "last seen 8d ago"
    provider: str = ""            # which provider surfaced it (for the UI)
    extra: dict = field(default_factory=dict)


class DiscoveryProvider:
    """Base class for all providers.

    Subclasses override `id`, `label`, `available`, and `list_hosts()`.
    `available` is False for providers that exist in the UI but aren't built
    yet (they show a 'coming soon' placeholder instead of hosts).
    """

    id: str = "base"
    label: str = "Base"
    #: user-facing one-liner shown when the provider has no hosts / isn't ready
    empty_message: str = "No hosts found."
    #: when False, the UI greys the provider out and shows `unavailable_message`
    available: bool = True
    unavailable_message: str = ""

    def list_hosts(self) -> list[Host]:
        """Return the currently reachable hosts. May block; callers run it
        off the main thread."""
        raise NotImplementedError

    # Optional hook: providers that need setup (login, server URL) can return
    # a reason string here to explain what's missing; None means ready.
    def readiness_error(self) -> Optional[str]:
        return None

    # Optional hook: a faster address for the same host (e.g. its LAN IP when
    # the overlay network routes directly over the LAN). "" means none.
    def direct_address(self, host: Host) -> str:
        return ""
