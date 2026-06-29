"""Tool registration entrypoints."""

from fastmcp import FastMCP

from google_ads_mcp.tools.accounts import register as register_account_tools
from google_ads_mcp.tools.diagnostics import register as register_diagnostic_tools
from google_ads_mcp.tools.metadata import register as register_metadata_tools
from google_ads_mcp.tools.query import register as register_query_tools
from google_ads_mcp.tools.reporting import register as register_reporting_tools


def register_tools(mcp: FastMCP) -> None:
    """Register all Google Ads MCP tools on the provided FastMCP app."""
    register_account_tools(mcp)
    register_reporting_tools(mcp)
    register_diagnostic_tools(mcp)
    register_query_tools(mcp)
    register_metadata_tools(mcp)
