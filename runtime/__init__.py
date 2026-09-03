"""DanceMate Runtime (v0.74).

LAN-only staging runtime for the ROCKPro64 deployment target.
Runtime state lives in PostgreSQL; the Information Engine keeps its own
SQLite persistence (hybrid persistence, see docs/README).
"""

__all__ = ["config"]
