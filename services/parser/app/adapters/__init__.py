"""Source adapters.

Concrete adapters are registered in :mod:`app.registry`.  Importing this
package must stay side-effect free so tests can construct individual adapters
without starting the service.
"""

from .base import BaseAdapter, RobotsPolicy, RobotsRule

__all__ = ["BaseAdapter", "RobotsPolicy", "RobotsRule"]
