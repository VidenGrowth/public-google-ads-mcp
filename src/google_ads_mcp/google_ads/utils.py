"""Formatting, validation, and GAQL utility helpers."""

from __future__ import annotations

import calendar
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, get_args


@dataclass(frozen=True)
class ResolvedDateRange:
    """Resolved GAQL date clause plus a response-friendly representation."""

    clause: str
    date_from: str | None = None
    date_to: str | None = None
    preset: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.preset:
            return {"preset": self.preset}
        return {"date_from": self.date_from, "date_to": self.date_to}


def fmt(data: Any) -> str:
    """Format data as compact JSON (used for non-tabular responses and errors)."""
    return json.dumps(data, separators=(",", ":"), default=str)


def _cell(value: Any) -> str:
    """Serialize a single cell value for TSV output."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        raw = "|".join(str(v) for v in value)
    elif isinstance(value, bool):
        raw = str(value).lower()
    else:
        raw = str(value)
    return raw.replace("\t", " ").replace("\n", " ").replace("\r", "")


def fmt_table(meta: dict[str, Any], rows: list[dict[str, Any]] | None = None, **named: list[dict[str, Any]]) -> str:
    """Format metadata as <meta>JSON</meta> + row data as <data>/<table> TSV blocks.

    Usage:
        fmt_table({"date_range": ...}, campaigns)                       # single → <data>
        fmt_table({"filters": ...}, age=age_rows, gender=gender_rows)   # multi → <table name="...">

    `date_range` and `filters` keys are pulled out of the caller's meta and
    nested under a new `applied` sub-object together with the computed
    `row_count`. Any other meta keys (e.g. `summary`, `query`, `truncated`,
    `month_start`) stay at the top level of the metadata JSON.
    """
    total = (len(rows) if rows is not None else 0) + sum(len(v) for v in named.values())

    applied: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in meta.items():
        if key in ("date_range", "filters"):
            applied[key] = value
        else:
            extras[key] = value
    applied["row_count"] = total
    meta_out: dict[str, Any] = {"applied": applied, **extras}

    parts = [f"<meta>{json.dumps(meta_out, separators=(',', ':'), default=str)}</meta>"]

    tables: dict[str, list[dict[str, Any]]] = {}
    if rows is not None:
        tables["data"] = rows
    tables.update(named)
    multi = len(tables) > 1

    for label, table_rows in tables.items():
        if not table_rows:
            continue
        headers = list(table_rows[0].keys())
        open_tag = f'<table name="{label}">' if multi else "<data>"
        close_tag = "</table>" if multi else "</data>"
        parts.append(open_tag)
        parts.append("\t".join(headers))
        for row in table_rows:
            parts.append("\t".join(_cell(row.get(h)) for h in headers))
        parts.append(close_tag)

    return "\n".join(parts)


def error_response(exc: Exception) -> str:
    """Format an error consistently for MCP tool callers."""
    return f"<error>{fmt({'error': str(exc)})}</error>"


def normalize_customer_id(customer_id: str) -> str:
    """Normalize a customer ID by stripping separators and validating digits."""
    normalized = "".join(ch for ch in str(customer_id).strip() if ch.isdigit())
    if not normalized:
        raise ValueError("customer_id must contain digits only.")
    return normalized


def normalize_numeric_id(value: str | None, name: str | None) -> str | None:
    """Validate numeric filter IDs used in GAQL WHERE clauses."""
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized.isdigit():
        raise ValueError(f"{name or 'Value'} must contain digits only.")
    return normalized


def normalize_positive_int(name: str, value: int | None) -> int | None:
    """Validate positive integer parameters."""
    if value is None:
        return None
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return value


def parse_iso_date(value: str, name: str) -> date:
    """Parse an ISO date or raise a validation error."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be in YYYY-MM-DD format.") from exc


def build_date_clause(
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ResolvedDateRange:
    """Build a GAQL date filter clause from explicit or relative inputs."""
    if (date_from and not date_to) or (date_to and not date_from):
        raise ValueError("date_from and date_to must be provided together.")

    if date_from and date_to:
        start = parse_iso_date(date_from, "date_from")
        end = parse_iso_date(date_to, "date_to")
        if start > end:
            raise ValueError("date_from must be on or before date_to.")
        return ResolvedDateRange(
            clause=f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'",
            date_from=start.isoformat(),
            date_to=end.isoformat(),
        )

    normalized_days = normalize_positive_int("date_range_days", date_range_days)
    if normalized_days:
        yesterday = date.today() - timedelta(days=1)
        start = yesterday - timedelta(days=normalized_days - 1)
        return ResolvedDateRange(
            clause=f"segments.date BETWEEN '{start.isoformat()}' AND '{yesterday.isoformat()}'",
            date_from=start.isoformat(),
            date_to=yesterday.isoformat(),
        )

    return ResolvedDateRange(clause="segments.date DURING LAST_30_DAYS", preset="LAST_30_DAYS")


def build_where(*clauses: str) -> str:
    """Join non-empty GAQL WHERE clauses with AND."""
    active_clauses = [clause for clause in clauses if clause]
    if not active_clauses:
        raise ValueError("At least one WHERE clause is required.")
    return " AND ".join(active_clauses)


# Friendly sort names → GAQL metric fields (available in virtually every tool).
SORT_FIELDS: dict[str, str] = {
    "cost": "metrics.cost_micros",
    "impressions": "metrics.impressions",
    "clicks": "metrics.clicks",
    "conversions": "metrics.conversions",
    "conversion_value": "metrics.conversions_value",
    "conversions_by_conversion_date": "metrics.conversions_by_conversion_date",
    "conversion_value_by_conversion_date": "metrics.conversions_value_by_conversion_date",
    "all_conversions": "metrics.all_conversions",
    "all_conversions_value": "metrics.all_conversions_value",
    "date": "segments.date"
}


def build_order_by(
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
    default: str | None = "metrics.cost_micros DESC",
) -> str:
    """Build a GAQL ORDER BY clause.

    Accepts a friendly alias from ``SORT_FIELDS`` (e.g. ``cost``) or a raw
    GAQL field containing a dot (e.g. ``campaign.name``).
    """

    if order_by is None:
        if default is None:
            return ""
        return f"ORDER BY {default}"

    key = order_by.strip()
    if "." in key:
        field = key
    else:
        field = SORT_FIELDS.get(key.lower())
        if not field:
            valid = ", ".join(SORT_FIELDS)
            raise ValueError(
                f"Unknown order_by alias '{order_by}'. Use one of: {valid} – "
                f"or pass a raw GAQL field like 'campaign.name'."
            )
    direction = "ASC" if sort_order.upper() == "ASC" else "DESC"
    return f"ORDER BY {field} {direction}"


def build_limit(limit: int | None = None) -> str:
    """Build a GAQL LIMIT clause.  Returns empty string when unlimited."""
    if limit is None:
        return ""
    if limit <= 0:
        raise ValueError("limit must be greater than 0.")
    return f"LIMIT {limit}"


def id_filter(field: str, value: str | list[str] | None) -> str:
    """Return a GAQL filter for numeric ID(s).  Single → ``=``, list → ``IN``."""
    if value is None:
        return ""
    if isinstance(value, list):
        ids = [normalize_numeric_id(v, field) for v in value]
        ids = [i for i in ids if i]
        if not ids:
            return ""
        return f"{field} IN ({', '.join(ids)})"
    normalized = normalize_numeric_id(value, field)
    return f"{field} = {normalized}" if normalized else ""


def _escape_like(value: str) -> str:
    """Escape GAQL LIKE special characters: % _ [ ]."""
    out = value.replace("[", "[[]")
    out = out.replace("]", "[]]")
    out = out.replace("%", "[%]")
    out = out.replace("_", "[_]")
    out = out.replace("'", "\\'")
    return out


def _escape_re2(value: str) -> str:
    """Escape RE2 metacharacters for use in REGEXP_MATCH."""
    meta = r"\.+*?^$|{}[]()"
    out = []
    for ch in value:
        if ch in meta:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out).replace("'", "\\'")


def name_filter(field: str, value: str | list[str] | None) -> str:
    """Return a GAQL name filter.

    Single string → ``LIKE '%value%'`` (case-insensitive contains).
    List of strings → ``REGEXP_MATCH '(?i).*(v1|v2).*'`` (contains any).
    """
    if not value:
        return ""
    if isinstance(value, list):
        parts = [v.strip() for v in value if v and v.strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return f"{field} LIKE '%{_escape_like(parts[0])}%'"
        alternatives = "|".join(_escape_re2(p) for p in parts)
        return f"{field} REGEXP_MATCH '(?i).*({alternatives}).*'"
    sanitized = _escape_like(value)
    return f"{field} LIKE '%{sanitized}%'"


# Status enum values (Google Ads API v23). Literal types are the source of
# truth for both parameter type hints and the frozensets consumed by
# `enum_filter`.
SortOrder = Literal["ASC", "DESC"]

CampaignStatus = Literal["ENABLED", "PAUSED", "REMOVED"]
CampaignPrimaryStatus = Literal[
    "ELIGIBLE", "PAUSED", "REMOVED", "ENDED", "PENDING",
    "MISCONFIGURED", "LIMITED", "LEARNING", "NOT_ELIGIBLE",
]
CampaignServingStatus = Literal["SERVING", "NONE", "ENDED", "PENDING", "SUSPENDED"]
AdGroupStatus = Literal["ENABLED", "PAUSED", "REMOVED"]
AdGroupPrimaryStatus = Literal[
    "ELIGIBLE", "PAUSED", "REMOVED", "PENDING", "NOT_ELIGIBLE", "LIMITED",
]
AssetGroupStatus = Literal["ENABLED", "PAUSED", "REMOVED"]
AssetGroupPrimaryStatus = Literal[
    "ELIGIBLE", "PAUSED", "REMOVED", "PENDING", "NOT_ELIGIBLE", "LIMITED",
]

CAMPAIGN_STATUSES = frozenset(get_args(CampaignStatus))
CAMPAIGN_PRIMARY_STATUSES = frozenset(get_args(CampaignPrimaryStatus))
CAMPAIGN_SERVING_STATUSES = frozenset(get_args(CampaignServingStatus))
AD_GROUP_STATUSES = frozenset(get_args(AdGroupStatus))
AD_GROUP_PRIMARY_STATUSES = frozenset(get_args(AdGroupPrimaryStatus))
ASSET_GROUP_STATUSES = frozenset(get_args(AssetGroupStatus))
ASSET_GROUP_PRIMARY_STATUSES = frozenset(get_args(AssetGroupPrimaryStatus))


def enum_filter(field: str, value: str | Sequence[str] | None, allowed: frozenset[str]) -> str:
    """Return a GAQL filter for an enum field.  Single → ``=``, list → ``IN``.

    Values are stripped, upper-cased, and validated against ``allowed``.
    Returns an empty string when the input is None/empty so callers can
    pipe the result through ``build_where`` unchanged.
    """
    if value is None:
        return ""
    values = [value] if isinstance(value, str) else list(value)
    cleaned = [str(v).strip().upper() for v in values if v and str(v).strip()]
    if not cleaned:
        return ""
    invalid = [v for v in cleaned if v not in allowed]
    if invalid:
        raise ValueError(
            f"Invalid {field} value(s): {invalid}. Allowed: {sorted(allowed)}"
        )
    if len(cleaned) == 1:
        return f"{field} = '{cleaned[0]}'"
    quoted = ", ".join(f"'{v}'" for v in cleaned)
    return f"{field} IN ({quoted})"


def health_payload(entity: Any) -> dict[str, Any]:
    """Extract status/primary_status/primary_status_reasons from a campaign or ad_group row."""
    return {
        "status": enum_name(entity.status),
        "primary_status": enum_name(entity.primary_status),
        "primary_status_reasons": [enum_name(r) for r in entity.primary_status_reasons],
    }


def status_clauses(
    *,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    asset_group_status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    asset_group_primary_status: AssetGroupPrimaryStatus | list[AssetGroupPrimaryStatus] | None = None,
    apply_campaign: bool = True,
    apply_ad_group: bool = True,
    apply_asset_group: bool = False,
) -> list[str]:
    """Build status + primary_status WHERE clauses with "exclude REMOVED" defaults.

    When a level's ``*_status`` arg is ``None`` the default ``!= 'REMOVED'``
    clause is emitted; otherwise it is validated via ``enum_filter``.
    ``primary_status`` has no default (None → no clause).

    Toggle ``apply_campaign`` / ``apply_ad_group`` / ``apply_asset_group``
    off when the tool's resource doesn't expose that level (e.g.
    campaign-only queries). ``apply_asset_group`` defaults to ``False``
    since only Performance Max / asset-group tools need it.
    """
    clauses: list[str] = []
    if apply_campaign:
        clauses.append(
            enum_filter("campaign.status", campaign_status, CAMPAIGN_STATUSES)
            if campaign_status is not None
            else "campaign.status != 'REMOVED'"
        )
        clauses.append(
            enum_filter("campaign.primary_status", campaign_primary_status, CAMPAIGN_PRIMARY_STATUSES)
        )
    if apply_ad_group:
        clauses.append(
            enum_filter("ad_group.status", ad_group_status, AD_GROUP_STATUSES)
            if ad_group_status is not None
            else "ad_group.status != 'REMOVED'"
        )
        clauses.append(
            enum_filter("ad_group.primary_status", ad_group_primary_status, AD_GROUP_PRIMARY_STATUSES)
        )
    if apply_asset_group:
        clauses.append(
            enum_filter("asset_group.status", asset_group_status, ASSET_GROUP_STATUSES)
            if asset_group_status is not None
            else "asset_group.status != 'REMOVED'"
        )
        clauses.append(
            enum_filter("asset_group.primary_status", asset_group_primary_status, ASSET_GROUP_PRIMARY_STATUSES)
        )
    return clauses


def cost_from_micros(cost_micros: float | int) -> float:
    """Convert micros to account currency units."""
    return round(float(cost_micros) / 1_000_000, 2)


def safe_divide(numerator: float | int, denominator: float | int, digits: int = 2) -> float | None:
    """Safely divide numbers and round the result."""
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), digits)


def safe_percentage(numerator: float | int, denominator: float | int) -> float:
    """Safely calculate a percentage."""
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, 2)


def enum_name(value: Any) -> str:
    """Return the enum name when available, otherwise stringify the value."""
    return getattr(value, "name", str(value))


def message_to_string(value: Any) -> Any:
    """Convert proto-ish values into JSON-serializable structures."""
    if value is None:
        return None
    if hasattr(value, "paths"):
        return list(value.paths)
    if isinstance(value, (list, tuple, set)):
        return [message_to_string(item) for item in value]
    return str(value)


def asset_payload(row: Any, scope: str) -> dict[str, Any]:
    """Normalize asset rows from campaign_asset/customer_asset queries."""
    payload: dict[str, Any] = {
        "scope": scope,
        "asset_id": str(row.asset.id),
        "asset_name": row.asset.name,
        "asset_type": enum_name(row.asset.type_),
        "field_type": enum_name(
            row.campaign_asset.field_type if scope == "campaign" else row.customer_asset.field_type
        ),
        "status": enum_name(row.campaign_asset.status if scope == "campaign" else row.customer_asset.status),
        "link_text": getattr(row.asset.sitelink_asset, "link_text", ""),
        "description1": getattr(row.asset.sitelink_asset, "description1", ""),
        "description2": getattr(row.asset.sitelink_asset, "description2", ""),
        "callout_text": getattr(row.asset.callout_asset, "callout_text", ""),
        "structured_snippet_header": getattr(row.asset.structured_snippet_asset, "header", ""),
        "structured_snippet_values": list(getattr(row.asset.structured_snippet_asset, "values", [])),
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
    }
    if scope == "campaign":
        payload["campaign_id"] = str(row.campaign.id)
        payload["campaign_name"] = row.campaign.name
        payload["cost"] = cost_from_micros(row.metrics.cost_micros)
        payload["ctr"] = safe_percentage(row.metrics.clicks, row.metrics.impressions)
    return payload


def today_month_context() -> tuple[date, date, int]:
    """Return current month start, yesterday, and days in month."""
    today = date.today()
    month_start = today.replace(day=1)
    yesterday = today - timedelta(days=1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    return month_start, yesterday, days_in_month
