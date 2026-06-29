"""HTTP helper for fetching external Google Ads reference pages."""

from __future__ import annotations

import urllib.request

_USER_AGENT = "Mozilla/5.0 (google-ads-mcp reference fetcher)"


def fetch_text(url: str, timeout: float = 15.0) -> str:
    """Fetch a URL and return its body as UTF-8 text."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")
