"""Persistent storage backends — SQLite-based cache + metadata stores.

Public modules:
  - db_cache         : unified SQLite-backed key/value cache (TTL, refresh-on-demand)
  - stock_meta_cache : A-share code→name + quote metadata (backed by db_cache)

The old JSON-on-disk helpers were replaced by the SQLite layer in `db_cache`.
"""

from . import db_cache  # noqa: F401
