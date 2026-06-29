"""Google Ads MCP Server - Gives Claude access to Google Ads account data."""

import os

from google_ads_mcp.app import create_mcp
from google_ads_mcp.observability import setup_logging


def main():
    setup_logging()
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        # The remote HTTP endpoint is always authenticated with per-user Google
        # OAuth – there is no unauthenticated HTTP mode. build_auth() raises if
        # the OAuth env vars are missing.
        from google_ads_mcp.auth import build_auth

        mcp = create_mcp(auth=build_auth())
        mcp.run(
            transport="http",
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8080")),
            path=os.getenv("MCP_HTTP_PATH", "/mcp/"),
            stateless_http=True,
        )
    else:
        mcp = create_mcp()
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
