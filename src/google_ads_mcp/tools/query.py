"""GAQL query tools: raw query runner and structured GAQL search builder."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.protobuf import descriptor
from fastmcp import FastMCP

from google_ads_mcp.google_ads.client import search_rows
from google_ads_mcp.google_ads.utils import error_response, fmt, fmt_table

_RESOURCES_FILE = Path(__file__).resolve().parent.parent / "resources" / "gaql_resources.txt"


@lru_cache(maxsize=1)
def _known_resources() -> frozenset[str]:
    """Return the set of known GAQL resource names, or empty if the file is missing."""
    try:
        return frozenset(line.strip() for line in _RESOURCES_FILE.read_text().splitlines() if line.strip())
    except OSError:
        return frozenset()


def _flatten(obj: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into dot-separated keys, preserving scalar types."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, full_key))
        else:
            out[full_key] = value
    return out


def _is_map_entry(field: descriptor.FieldDescriptor) -> bool:
    """Return whether the field is a protobuf map entry."""
    return (
        field.type == descriptor.FieldDescriptor.TYPE_MESSAGE
        and field.message_type.has_options
        and field.message_type.GetOptions().map_entry
    )


def _field_to_python(field: descriptor.FieldDescriptor, value: Any) -> Any:
    """Convert a protobuf field value to a Python value without JSON stringification."""
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_MESSAGE:
        return _message_to_python(value)
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_ENUM:
        if field.enum_type.full_name == "google.protobuf.NullValue":
            return None
        enum_value = field.enum_type.values_by_number.get(value)
        return enum_value.name if enum_value is not None else value
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_STRING:
        if field.type == descriptor.FieldDescriptor.TYPE_BYTES:
            return base64.b64encode(value).decode("utf-8")
        return str(value)
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_BOOL:
        return bool(value)
    if field.cpp_type in {
        descriptor.FieldDescriptor.CPPTYPE_INT32,
        descriptor.FieldDescriptor.CPPTYPE_UINT32,
        descriptor.FieldDescriptor.CPPTYPE_INT64,
        descriptor.FieldDescriptor.CPPTYPE_UINT64,
    }:
        return int(value)
    if field.cpp_type in {
        descriptor.FieldDescriptor.CPPTYPE_FLOAT,
        descriptor.FieldDescriptor.CPPTYPE_DOUBLE,
    }:
        return float(value)
    return value


def _message_to_python(message: Any) -> dict[str, Any]:
    """Convert a protobuf message to nested Python types, preserving numeric scalars."""
    data: dict[str, Any] = {}
    for field, value in message.ListFields():
        name = field.name
        if _is_map_entry(field):
            value_field = field.message_type.fields_by_name["value"]
            data[name] = {key: _field_to_python(value_field, value[key]) for key in value}
        elif field.is_repeated:
            data[name] = [_field_to_python(field, item) for item in value]
        else:
            data[name] = _field_to_python(field, value)
    return data


def _row_to_flat(row) -> dict[str, Any]:
    """Convert a proto-plus row to a flat dict of dot-separated keys."""
    return _flatten(_message_to_python(row._pb))


def _build_gaql(
    resource: str,
    fields: list[str],
    conditions: list[str] | None,
    orderings: list[str] | None,
    limit: int | None,
) -> str:
    """Assemble a GAQL SELECT query from structured parts."""
    if not resource or not resource.strip():
        raise ValueError("resource must be a non-empty string.")
    if not fields:
        raise ValueError("fields must contain at least one field name.")

    parts = [f"SELECT {', '.join(fields)}", f"FROM {resource.strip()}"]
    if conditions:
        parts.append("WHERE " + " AND ".join(conditions))
    if orderings:
        parts.append("ORDER BY " + ", ".join(orderings))
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be greater than 0.")
        parts.append(f"LIMIT {limit}")
    return " ".join(parts)


def _run_gaql_query(customer_id: str, query: str, login_customer_id: str | None = None) -> list[dict[str, Any]]:
    """Helper for run_gaql_query: executes the query and formats results."""
    rows = search_rows(customer_id, query, login_customer_id)
    return [_row_to_flat(row) for row in rows]


def run_gaql_query(
    customer_id: str,
    query: str,
    login_customer_id: str | None = None,
    max_rows: int = 1000,
) -> str:
    """Execute a raw GAQL SELECT query. Escape hatch for anything other tools don't cover.

    Prefer the structured `gaql_search` tool when the shape is known. Use this
    when you need complex WHERE/ORDER BY clauses, GAQL-specific features
    (DURING, CONTAINS, REGEXP_MATCH, etc.), or segments not exposed via
    other tools. Only SELECT is allowed – mutations are blocked.

    Discovery workflow:
      1. `get_resource_metadata("campaign")` for valid fields.
      2. Consult `resource://metrics` / `resource://segments` for metric
         and segment compatibility.
      3. Write the query with literal dates ('YYYY-MM-DD', no TODAY).

    Args:
        customer_id: Google Ads customer ID (with or without dashes).
        query: A GAQL SELECT statement. Must start with "SELECT".
        max_rows: Row cap (default 1000, clamped to 1..10000). Result
            includes `truncated: true` when the underlying query returned
            more rows than max_rows.

    Returns: metadata line ({truncated}) + TSV rows with fields flattened
    to dot-separated column names.
    """
    try:
        normalized = query.strip()
        if not normalized.upper().startswith("SELECT"):
            return fmt({"error": "Only SELECT queries are allowed."})

        flat_results = _run_gaql_query(customer_id, normalized, login_customer_id)
        flat_results_truncated = flat_results[:max_rows] if max_rows > 0 else flat_results

        return fmt_table({"truncated": len(flat_results) > max_rows}, flat_results_truncated)
    except Exception as exc:
        return error_response(exc)


def gaql_search(
    customer_id: str,
    resource: str,
    fields: list[str],
    login_customer_id: str | None = None,
    conditions: list[str] | None = None,
    orderings: list[str] | None = None,
    limit: int | None = None,
) -> str:
    """Structured GAQL builder: assembles SELECT/FROM/WHERE/ORDER BY/LIMIT and runs it.

    Prefer this over `run_gaql_query` when the resource and fields are
    known – safer (resource validated against a known list) and clearer
    than raw GAQL. Fall back to `run_gaql_query` for features this
    builder doesn't cover.

    Discovery workflow:
      1. `get_resource_metadata(resource)` to list valid fields.
      2. Consult `resource://metrics` / `resource://segments` for metric
         and segment compatibility with the chosen resource.

    Args:
        customer_id: Google Ads customer ID (with or without dashes).
        resource: FROM clause name, e.g. "campaign", "ad_group",
            "keyword_view", "search_term_view". Validated against the
            bundled list; call `get_resource_metadata` if unsure.
        fields: SELECT list, e.g. ["campaign.id", "campaign.name",
            "metrics.clicks", "metrics.cost_micros"]. At least one field.
        conditions: WHERE predicates combined with AND, e.g.
            ["campaign.status = 'ENABLED'",
             "segments.date BETWEEN '2026-03-01' AND '2026-03-31'"].
            Use literal 'YYYY-MM-DD' dates (no date literals like TODAY).
        orderings: ORDER BY clauses, e.g. ["metrics.clicks DESC",
            "campaign.name ASC"].
        limit: Max rows. `change_event` requires limit <= 10000.

    Returns: metadata line ({query}) + TSV rows with fields flattened to
    dot-separated column names.
    """
    try:
        known = _known_resources()
        if known and resource.strip() not in known:
            return fmt(
                {
                    "error": f"Unknown resource '{resource}'. "
                    "Use `get_resource_metadata` or check resource://discovery "
                    "to find valid resources.",
                }
            )

        query = _build_gaql(resource, fields, conditions, orderings, limit)
        rows = search_rows(customer_id, query, login_customer_id)
        flat_results = [_row_to_flat(row) for row in rows]
        return fmt_table({"query": query}, flat_results)
    except Exception as exc:
        return error_response(exc)


TOOLS = (run_gaql_query, gaql_search)


def register(mcp: FastMCP) -> None:
    """Register GAQL query tools."""
    from google_ads_mcp.observability import log_tool_call

    for fn in TOOLS:
        mcp.tool()(log_tool_call(fn))
