"""Field metadata discovery tool backed by GoogleAdsFieldService."""

from __future__ import annotations

from functools import lru_cache

from fastmcp import FastMCP

from google_ads_mcp.google_ads.client import require_client
from google_ads_mcp.google_ads.utils import error_response, fmt


@lru_cache(maxsize=256)
def _fetch_resource_fields(resource: str) -> dict:
    """Query GoogleAdsFieldService for fields belonging to a resource."""
    client = require_client()
    field_service = client.get_service("GoogleAdsFieldService")

    query = f"SELECT name, selectable, filterable, sortable WHERE name LIKE '{resource}.%'"
    try:
        response = field_service.search_google_ads_fields(query=query)
        results = list(response)
    except Exception:
        fallback_query = "SELECT name, selectable, filterable, sortable"
        response = field_service.search_google_ads_fields(query=fallback_query)
        prefix = f"{resource}."
        results = [row for row in response if row.name.startswith(prefix)]

    selectable, filterable, sortable = [], [], []
    for row in results:
        if row.selectable:
            selectable.append(row.name)
        if row.filterable:
            filterable.append(row.name)
        if row.sortable:
            sortable.append(row.name)

    return {
        "resource": resource,
        "selectable_fields": sorted(selectable),
        "filterable_fields": sorted(filterable),
        "sortable_fields": sorted(sortable),
    }


def get_resource_metadata(resource: str) -> str:
    """List selectable, filterable, and sortable fields for a Google Ads resource.

    Use this before `gaql_search` or `run_gaql_query` to discover valid field
    names for SELECT / WHERE / ORDER BY clauses and to verify a field
    exists before using it. Results are cached in-process (metadata rarely
    changes).

    Args:
        resource: Google Ads resource name – e.g. "campaign", "ad_group",
            "keyword_view", "search_term_view", "customer", "ad_group_ad".
            Do NOT include the "resource://" prefix, a leading dot, or a
            trailing dot.

    Returns: JSON object with `resource`, `selectable_fields` (usable in
    SELECT), `filterable_fields` (usable in WHERE), `sortable_fields`
    (usable in ORDER BY). Each list is sorted alphabetically.
    """
    try:
        name = (resource or "").strip().strip(".")
        if not name:
            return fmt({"error": "resource must be a non-empty string."})
        return fmt(_fetch_resource_fields(name))
    except Exception as exc:
        return error_response(exc)


TOOLS = (get_resource_metadata,)


def register(mcp: FastMCP) -> None:
    """Register field metadata tools."""
    from google_ads_mcp.observability import log_tool_call

    for fn in TOOLS:
        mcp.tool()(log_tool_call(fn))
