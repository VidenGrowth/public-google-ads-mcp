"""MCP resource registration entrypoints."""

from fastmcp import FastMCP

from google_ads_mcp.resources.discovery import register as register_discovery
from google_ads_mcp.resources.metrics import register as register_metrics
from google_ads_mcp.resources.release_notes import register as register_release_notes
from google_ads_mcp.resources.segments import register as register_segments


def register_resources(mcp: FastMCP) -> None:
    """Register all Google Ads MCP resources on the provided FastMCP app."""
    register_discovery(mcp)
    register_metrics(mcp)
    register_segments(mcp)
    register_release_notes(mcp)
