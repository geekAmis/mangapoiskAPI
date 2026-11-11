"""MangaPoisk Reborn — shared building blocks.

The package deliberately has no knowledge about concrete services.  It only
contains contracts, configuration, logging, persistence helpers and the
small amount of security code that every FastAPI service needs.
"""

from .version import __version__

__all__ = ["__version__"]
