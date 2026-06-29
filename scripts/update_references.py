"""Regenerate src/google_ads_mcp/resources/gaql_resources.txt from the live API.

Usage:
    python scripts/update_references.py

Reads credentials from the same environment variables as the MCP server
(GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET,
GOOGLE_ADS_REFRESH_TOKEN, GOOGLE_ADS_LOGIN_CUSTOMER_ID), or from a
google-ads.yaml file referenced by GOOGLE_ADS_CONFIGURATION_FILE_PATH.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from google_ads_mcp.google_ads.client import require_client  # noqa: E402

OUTPUT_FILE = REPO_ROOT / "src" / "google_ads_mcp" / "resources" / "gaql_resources.txt"


def fetch_resource_names() -> list[str]:
    """Query GoogleAdsFieldService for all resources."""
    client = require_client()
    field_service = client.get_service("GoogleAdsFieldService")
    query = "SELECT name WHERE category = 'RESOURCE'"
    response = field_service.search_google_ads_fields(query=query)
    return sorted({row.name for row in response})


def main() -> int:
    load_dotenv()
    try:
        resources = fetch_resource_names()
    except Exception as exc:
        print(f"Failed to fetch resource list: {exc}", file=sys.stderr)
        return 1

    if not resources:
        print("No resources returned from GoogleAdsFieldService.", file=sys.stderr)
        return 1

    OUTPUT_FILE.write_text("\n".join(resources) + "\n", encoding="utf-8")
    print(f"Wrote {len(resources)} resources to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
