"""Google Ads segments reference resource."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.resources._fetch import fetch_text

SEGMENTS_URL = "https://developers.google.com/google-ads/api/fields/latest/segments"


def register(mcp: FastMCP) -> None:
    """Register the segments reference resource."""

    @mcp.resource(
        "resource://segments",
        name="google_ads_segments",
        description=(
            "Official reference for segments available in the Google Ads API. "
            "Segments partition metrics along dimensions (date, device, network, etc.) "
            "and have strict compatibility rules with resources and metrics. Consult "
            "before adding a segments.* field to a GAQL query."
        ),
        mime_type="text/html",
    )
    def segments() -> str:
        return fetch_text(SEGMENTS_URL)
