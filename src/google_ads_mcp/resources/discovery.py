"""Google Ads API discovery document resource."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.resources._fetch import fetch_text

DISCOVERY_URL = "https://googleads.googleapis.com/$discovery/rest?version=v21"


def register(mcp: FastMCP) -> None:
    """Register the API discovery document resource."""

    @mcp.resource(
        "resource://discovery",
        name="google_ads_discovery",
        description=(
            "Google Ads API discovery document (JSON). Describes all REST resources, "
            "methods, and schemas exposed by the API. Useful for grounding GAQL queries "
            "and tool calls in the authoritative API surface."
        ),
        mime_type="application/json",
    )
    def discovery() -> str:
        return fetch_text(DISCOVERY_URL)
