"""Shared constants for tool implementations."""

from __future__ import annotations

# Default LIMIT applied by every tool that calls build_limit() when the
# caller does not pass an explicit `limit`. Callers can always override
# (smaller for previews, larger for full pulls) up to the Google Ads API
# server-side cap.
DEFAULT_LIMIT = 5000
