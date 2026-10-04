"""Provider registry. Order here is the order shown in the UI dropdown."""
from .base import DiscoveryProvider, Host
from .tailscale import TailscaleProvider
from .selfhosted import SelfHostedProvider

ALL_PROVIDERS = [TailscaleProvider, SelfHostedProvider]

__all__ = ["DiscoveryProvider", "Host", "TailscaleProvider",
           "SelfHostedProvider", "ALL_PROVIDERS"]
