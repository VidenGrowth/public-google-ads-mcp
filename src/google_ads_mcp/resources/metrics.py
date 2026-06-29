"""Google Ads metrics reference resource."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.resources._fetch import fetch_text

METRICS_URL = "https://developers.google.com/google-ads/api/fields/latest/metrics"


def register(mcp: FastMCP) -> None:
    """Register the metrics reference resource."""

    @mcp.resource(
        "resource://metrics",
        name="google_ads_metrics",
        description=(
            "Official reference for metrics available in the Google Ads API. "
            "Enumerates every metric (e.g. metrics.clicks, metrics.cost_micros, "
            "metrics.conversions) and describes how each one is calculated. Consult "
            "before choosing metrics for a GAQL SELECT clause."
        ),
        mime_type="text/html",
    )
    def metrics() -> str:
        return fetch_text(METRICS_URL)
