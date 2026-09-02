"""Controlled pilot execution service.

The package deliberately uses only Python's standard library.  It is deployed
as a separate, non-business container and exposes a very small HTTPS API.
"""

__all__ = ["app"]
