"""Local smoke test for the Google Ads MCP server.

Run after filling in .env:

    uv run python scripts/smoke_test.py

Step 1 needs no credentials and confirms the server wires up (tools register).
Step 2 hits the live Google Ads API using your .env credentials and prints the
response – or the tool's error envelope if credentials are missing/invalid.
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

from google_ads_mcp.app import create_mcp


async def main() -> None:
    async with Client(create_mcp()) as client:
        tools = await client.list_tools()
        print(f"✓ server wired up – {len(tools)} tools registered")

        print("\nCalling get_accessible_accounts (uses your live credentials)…\n")
        result = await client.call_tool("get_accessible_accounts", {})
        text = getattr(result, "data", None)
        if not text:
            text = "\n".join(
                getattr(block, "text", "") for block in getattr(result, "content", [])
            )
        print(text or "(empty response)")


if __name__ == "__main__":
    asyncio.run(main())
