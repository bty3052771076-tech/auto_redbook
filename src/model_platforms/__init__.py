"""Local model connections, verified role resolution and protocol runtime."""

from .store import PlatformError, PlatformStore
from .runtime import RuntimeClient

__all__ = ['PlatformError', 'PlatformStore', 'RuntimeClient']
