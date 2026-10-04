"""Provider registry. Order here is the order shown in the UI dropdown."""
from .base import DiscoveryProvider, Host
from .tailscale import TailscaleProvider
from .local import LocalProvider
from .auto import AutoProvider
from .selfhosted import SelfHostedProvider

ALL_PROVIDERS = [AutoProvider, LocalProvider, TailscaleProvider, SelfHostedProvider]

__all__ = ["DiscoveryProvider", "Host", "TailscaleProvider",
           "SelfHostedProvider", "LocalProvider", "AutoProvider", "ALL_PROVIDERS"]
