"""Google Ads API release notes resource."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.resources._fetch import fetch_text

RELEASE_NOTES_URL = "https://developers.google.com/google-ads/api/docs/release-notes"


def register(mcp: FastMCP) -> None:
    """Register the release notes resource."""

    @mcp.resource(
        "resource://release-notes",
        name="google_ads_release_notes",
        description=(
            "Official Google Ads API release notes. Lists recent version changes, "
            "new fields, deprecations, and breaking changes. Consult when a feature "
            "or field appears to be missing or behaves unexpectedly."
        ),
        mime_type="text/html",
    )
    def release_notes() -> str:
        return fetch_text(RELEASE_NOTES_URL)
