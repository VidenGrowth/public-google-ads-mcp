"""Reporting and segmentation tools."""

from fastmcp import FastMCP

from google_ads_mcp.google_ads.client import search_rows
from google_ads_mcp.google_ads.utils import (
    AdGroupPrimaryStatus,
    AdGroupStatus,
    AssetGroupPrimaryStatus,
    AssetGroupStatus,
    CampaignPrimaryStatus,
    CampaignStatus,
    SortOrder,
    build_date_clause,
    build_limit,
    build_order_by,
    build_where,
    cost_from_micros,
    enum_filter,
    enum_name,
    error_response,
    fmt_table,
    health_payload,
    id_filter,
    name_filter,
    normalize_positive_int,
    safe_divide,
    safe_percentage,
    status_clauses,
)
from google_ads_mcp.tools.constants import DEFAULT_LIMIT


def get_campaigns_report(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_name: str | list[str] | None = None,
    status: CampaignStatus | list[CampaignStatus] | None = None,
    primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """List campaigns with budget, health, and performance metrics for the date range.

    Use when the question is "which campaigns are running / spending / converting"
    or "why isn't this campaign delivering". Default ordering: cost DESC.
    By default ``REMOVED`` campaigns are excluded – pass ``status=["REMOVED"]``
    (or include it in a list) to include them.

    Args:
        status: filter by user state. One of ENABLED, PAUSED, REMOVED, or a list.
        primary_status: filter by actual delivery state. One of ELIGIBLE, PAUSED,
            REMOVED, ENDED, PENDING, MISCONFIGURED, LIMITED, LEARNING,
            NOT_ELIGIBLE, or a list.

    Returns per campaign: campaign_id, campaign_name, status, primary_status,
    primary_status_reasons (pipe-joined; empty when ELIGIBLE), end_date
    (empty if open-ended), type (advertising_channel_type), daily_budget,
    impressions, clicks, cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=status,
                campaign_primary_status=primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                campaign.id, campaign.name,
                campaign.status, campaign.primary_status, campaign.primary_status_reasons,
                campaign.end_date_time,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        campaigns = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            end_date_time = row.campaign.end_date_time or ""
            campaigns.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    **health_payload(row.campaign),
                    "end_date": end_date_time[:10],
                    "type": enum_name(row.campaign.advertising_channel_type),
                    "daily_budget": cost_from_micros(row.campaign_budget.amount_micros),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_name": campaign_name,
                    "status": status,
                    "primary_status": primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            campaigns,
        )
    except Exception as exc:
        return error_response(exc)


def get_ad_groups_report(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    status: AdGroupStatus | list[AdGroupStatus] | None = None,
    primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """List ad groups with CPC bid, health, and performance metrics.

    Use to drill one level below campaigns, or to compare ad group
    efficiency within a campaign. By default ``REMOVED`` ad groups and
    ``REMOVED`` parent campaigns are excluded – pass the corresponding
    status=["REMOVED"] to include them.

    Args:
        status: ad_group user state. One of ENABLED, PAUSED, REMOVED, or a list.
        primary_status: ad_group delivery state. One of ELIGIBLE, PAUSED,
            REMOVED, PENDING, NOT_ELIGIBLE, LIMITED, or a list.
        campaign_status: parent campaign user state. Same values as ``status``.
        campaign_primary_status: parent campaign delivery state. One of
            ELIGIBLE, PAUSED, REMOVED, ENDED, PENDING, MISCONFIGURED, LIMITED,
            LEARNING, NOT_ELIGIBLE, or a list.

    Returns per ad group: campaign_id/name, ad_group_id/name, status,
    primary_status, primary_status_reasons (pipe-joined), cpc_bid,
    impressions, clicks, cost, conversions, ctr (%), cpa.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=status,
                ad_group_primary_status=primary_status,
            ),
        )
        query = f"""
            SELECT
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                ad_group.status, ad_group.primary_status, ad_group.primary_status_reasons,
                ad_group.cpc_bid_micros,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions
            FROM ad_group
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        ad_groups = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            ad_groups.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    **health_payload(row.ad_group),
                    "cpc_bid": cost_from_micros(row.ad_group.cpc_bid_micros),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "ad_group_name": ad_group_name,
                    "status": status,
                    "primary_status": primary_status,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            ad_groups,
        )
    except Exception as exc:
        return error_response(exc)


_KEYWORD_AGG_SORT_KEYS = {
    "cost": lambda r: r.get("cost") or 0,
    "impressions": lambda r: r.get("impressions") or 0,
    "clicks": lambda r: r.get("clicks") or 0,
    "conversions": lambda r: r.get("conversions") or 0,
}


_DIMENSION_AGG_SORT_KEYS = {
    "cost": lambda r: r.get("cost") or 0,
    "impressions": lambda r: r.get("impressions") or 0,
    "clicks": lambda r: r.get("clicks") or 0,
    "conversions": lambda r: r.get("conversions") or 0,
    "conversion_value": lambda r: r.get("conversion_value") or 0,
}


def _get_keywords(
    customer_id: str,
    *,
    group_level: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Shared keyword reporting core.

    ``group_level`` controls output granularity:
      - ``"keyword"``: aggregate across all parents – one row per keyword_text.
      - ``"campaign"``: one row per (campaign, keyword_text).
      - ``"ad_group"``: per-criterion detail (no aggregation).
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        normalized_limit = normalize_positive_int("limit", limit)
        where_clause = build_where(
            "ad_group_criterion.type = 'KEYWORD'",
            "ad_group_criterion.negative = FALSE",
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        filters_meta = {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "ad_group_id": ad_group_id,
            "ad_group_name": ad_group_name,
            "campaign_status": campaign_status,
            "campaign_primary_status": campaign_primary_status,
            "ad_group_status": ad_group_status,
            "ad_group_primary_status": ad_group_primary_status,
        }
        meta = {"filters": filters_meta, "date_range": date_range.as_dict(), "group_level": group_level}

        if group_level == "ad_group":
            query = f"""
                SELECT
                    campaign.id, campaign.name,
                    ad_group.id, ad_group.name,
                    ad_group_criterion.keyword.text,
                    ad_group_criterion.keyword.match_type,
                    ad_group_criterion.status,
                    ad_group_criterion.quality_info.quality_score,
                    ad_group_criterion.effective_cpc_bid_micros,
                    metrics.impressions, metrics.clicks, metrics.cost_micros,
                    metrics.conversions
                FROM keyword_view
                WHERE {where_clause}
                {build_order_by(order_by, sort_order)}
                {build_limit(normalized_limit or DEFAULT_LIMIT)}
            """
            rows_out = []
            for row in search_rows(customer_id, query, login_customer_id):
                cost = cost_from_micros(row.metrics.cost_micros)
                rows_out.append(
                    {
                        "campaign_id": str(row.campaign.id),
                        "campaign_name": row.campaign.name,
                        "ad_group_id": str(row.ad_group.id),
                        "ad_group_name": row.ad_group.name,
                        "keyword_text": row.ad_group_criterion.keyword.text,
                        "match_type": enum_name(row.ad_group_criterion.keyword.match_type),
                        "status": enum_name(row.ad_group_criterion.status),
                        "quality_score": row.ad_group_criterion.quality_info.quality_score,
                        "cpc_bid": cost_from_micros(row.ad_group_criterion.effective_cpc_bid_micros),
                        "impressions": row.metrics.impressions,
                        "clicks": row.metrics.clicks,
                        "cost": cost,
                        "conversions": row.metrics.conversions,
                        "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                        "cpa": safe_divide(cost, row.metrics.conversions),
                    }
                )
            return fmt_table(meta, rows_out)

        # keyword / campaign → aggregate in Python (GAQL doesn't aggregate implicitly).
        if group_level == "campaign":
            select_line = "campaign.id, campaign.name, ad_group_criterion.keyword.text,"
        else:
            select_line = "ad_group_criterion.keyword.text,"
        query = f"""
            SELECT
                {select_line}
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions
            FROM keyword_view
            WHERE {where_clause}
        """
        buckets: dict[tuple, dict] = {}
        for row in search_rows(customer_id, query, login_customer_id):
            text = row.ad_group_criterion.keyword.text
            if group_level == "campaign":
                key = (str(row.campaign.id), row.campaign.name, text)
            else:
                key = (text,)
            bucket = buckets.setdefault(
                key,
                {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0.0},
            )
            bucket["impressions"] += row.metrics.impressions
            bucket["clicks"] += row.metrics.clicks
            bucket["cost_micros"] += row.metrics.cost_micros
            bucket["conversions"] += row.metrics.conversions

        rows_out = []
        for key, bucket in buckets.items():
            cost = cost_from_micros(bucket["cost_micros"])
            row_out: dict[str, object] = {}
            if group_level == "campaign":
                row_out["campaign_id"] = key[0]
                row_out["campaign_name"] = key[1]
                row_out["keyword_text"] = key[2]
            else:
                row_out["keyword_text"] = key[0]
            row_out.update(
                {
                    "impressions": bucket["impressions"],
                    "clicks": bucket["clicks"],
                    "cost": cost,
                    "conversions": bucket["conversions"],
                    "ctr": safe_percentage(bucket["clicks"], bucket["impressions"]),
                    "cpa": safe_divide(cost, bucket["conversions"]),
                }
            )
            rows_out.append(row_out)

        # Sort the aggregated output (GAQL ORDER BY can't see aggregates).
        sort_key = _KEYWORD_AGG_SORT_KEYS.get((order_by or "cost").lower())
        if sort_key is None:
            valid = ", ".join(_KEYWORD_AGG_SORT_KEYS)
            raise ValueError(
                f"Invalid order_by '{order_by}' for aggregated keyword report. "
                f"Valid: {valid}."
            )
        rows_out.sort(key=sort_key, reverse=(sort_order.upper() != "ASC"))
        rows_out = rows_out[: normalized_limit or DEFAULT_LIMIT]

        return fmt_table(meta, rows_out)
    except Exception as exc:
        return error_response(exc)


def get_keywords_overall(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Total keyword performance summed across all campaigns and ad groups.

    One row per keyword_text. Use when comparing keywords on absolute
    spend/clicks regardless of where they are placed, e.g. "what's my
    total cost on the word 'running shoes'". For per-campaign breakdown
    use `get_keywords_by_campaign`; for full per-criterion detail with
    match_type/quality_score/bid use `get_keywords_by_ad_group`.

    Excludes negative and non-KEYWORD criteria. Rows under ``REMOVED``
    campaigns/ad groups are excluded by default – override via
    ``campaign_status`` / ``ad_group_status``. ``order_by`` accepts
    ``cost`` (default) / ``impressions`` / ``clicks`` / ``conversions``.

    Returns per keyword: keyword_text, impressions, clicks, cost,
    conversions, ctr (%), cpa.
    """
    return _get_keywords(
        customer_id,
        group_level="keyword",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_keywords_by_campaign(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Keyword performance broken down by parent campaign.

    One row per (campaign, keyword_text). Use to see how a keyword
    performs across your campaigns, or which campaigns use a keyword.
    For criterion-level detail (match_type, quality_score, bid) use
    `get_keywords_by_ad_group`.

    Same filtering/defaults as `get_keywords`. ``order_by`` accepts
    ``cost`` (default) / ``impressions`` / ``clicks`` / ``conversions``.

    Returns per row: campaign_id, campaign_name, keyword_text,
    impressions, clicks, cost, conversions, ctr (%), cpa.
    """
    return _get_keywords(
        customer_id,
        group_level="campaign",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_keywords_by_ad_group(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Per-criterion keyword detail: one row per (ad_group, keyword instance).

    Each ad-group/keyword pair may appear more than once if it exists at
    several match types. Use for keyword-level audit and optimization –
    includes match_type, status, quality_score, and effective CPC bid
    that the aggregated reports drop because they vary across criteria.

    For summed performance across ad groups use `get_keywords` or
    `get_keywords_by_campaign`. Same filtering/defaults as the siblings.

    Returns per row: campaign_id/name, ad_group_id/name, keyword_text,
    match_type (EXACT/PHRASE/BROAD), status, quality_score (1-10),
    cpc_bid, impressions, clicks, cost, conversions, ctr (%), cpa.
    """
    return _get_keywords(
        customer_id,
        group_level="ad_group",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


_DAILY_AGG_SORT_KEYS = {
    "date": lambda r: r.get("date") or "",
    "cost": lambda r: r.get("cost") or 0,
    "impressions": lambda r: r.get("impressions") or 0,
    "clicks": lambda r: r.get("clicks") or 0,
    "conversions": lambda r: r.get("conversions") or 0,
    "conversion_value": lambda r: r.get("conversion_value") or 0,
}


def get_daily_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "ASC",
) -> str:
    """Daily totals across all campaigns – one row per day.

    Use for trend/seasonality analysis, week-over-week comparisons, or
    spotting specific dates with spend/conversion anomalies. Campaign
    filters still apply – they narrow the set that's aggregated, but the
    output has no campaign split. Default ordering: date ASC. REMOVED
    campaigns are excluded by default.

    Returns one row per day: date, impressions, clicks, cost, conversions,
    conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        normalized_limit = normalize_positive_int("limit", limit)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                segments.date,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE {where_clause}
        """
        buckets: dict[str, dict] = {}
        for row in search_rows(customer_id, query, login_customer_id):
            date_str = str(row.segments.date)
            bucket = buckets.setdefault(
                date_str,
                {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0.0, "conversion_value": 0.0},
            )
            bucket["impressions"] += row.metrics.impressions
            bucket["clicks"] += row.metrics.clicks
            bucket["cost_micros"] += row.metrics.cost_micros
            bucket["conversions"] += row.metrics.conversions
            bucket["conversion_value"] += row.metrics.conversions_value

        daily_metrics = []
        for date_str, bucket in buckets.items():
            cost = cost_from_micros(bucket["cost_micros"])
            daily_metrics.append(
                {
                    "date": date_str,
                    "impressions": bucket["impressions"],
                    "clicks": bucket["clicks"],
                    "cost": cost,
                    "conversions": bucket["conversions"],
                    "conversion_value": bucket["conversion_value"],
                    "ctr": safe_percentage(bucket["clicks"], bucket["impressions"]),
                    "cpa": safe_divide(cost, bucket["conversions"]),
                    "roas": safe_divide(bucket["conversion_value"], cost),
                }
            )

        sort_key = _DAILY_AGG_SORT_KEYS.get((order_by or "date").lower())
        if sort_key is None:
            valid = ", ".join(_DAILY_AGG_SORT_KEYS)
            raise ValueError(
                f"Invalid order_by '{order_by}' for aggregated daily report. "
                f"Valid: {valid}."
            )
        daily_metrics.sort(key=sort_key, reverse=(sort_order.upper() != "ASC"))
        daily_metrics = daily_metrics[: normalized_limit or DEFAULT_LIMIT]

        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            daily_metrics,
        )
    except Exception as exc:
        return error_response(exc)


def get_daily_performance_by_campaign(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Daily performance per campaign – one row per (date, campaign).

    Use when you need to see which campaigns drove a day's totals – e.g.
    isolating a spike to a specific campaign, or comparing campaign-level
    trajectories over time. Default ordering: date ASC, then cost DESC.
    REMOVED campaigns are excluded by default.

    Returns per row: date, campaign_id, campaign_name, impressions, clicks,
    cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                segments.date,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order, default="segments.date ASC, metrics.cost_micros DESC")}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        daily_metrics = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            daily_metrics.append(
                {
                    "date": str(row.segments.date),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            daily_metrics,
        )
    except Exception as exc:
        return error_response(exc)


_CONVERSION_AGG_SORT_KEYS = {
    "conversions": lambda r: r.get("conversions") or 0,
    "conversion_value": lambda r: r.get("conversion_value") or 0,
    "conversions_by_conversion_date": lambda r: r.get("conversions_by_conversion_date") or 0,
    "conversion_value_by_conversion_date": lambda r: r.get("conversion_value_by_conversion_date") or 0,
    "all_conversions": lambda r: r.get("all_conversions") or 0,
    "all_conversions_value": lambda r: r.get("all_conversions_value") or 0,
    "date": lambda r: r.get("date") or "",
}


def _conversion_action_id_from_resource(resource_name: str) -> str:
    """Parse the numeric id from a conversion_action resource name.

    ``segments.conversion_action`` is returned as
    ``customers/<cid>/conversionActions/<id>``. The trailing segment is the
    numeric id the rest of the Google Ads surface uses.
    """
    return resource_name.rsplit("/", 1)[-1] if resource_name else ""


def _get_conversion_breakdown(
    customer_id: str,
    *,
    group_level: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Shared conversion-breakdown core.

    ``segments.conversion_action`` is incompatible with cost / impressions /
    clicks metrics, so this tool intentionally omits them and returns only
    conversion metrics (click-date and conversion-date variants plus
    all-conversions).

    ``group_level`` controls output granularity:
      - ``"overall"``: one row per conversion_action, aggregated across
        campaigns and dates.
      - ``"campaign"``: one row per (campaign, conversion_action).
      - ``"daily"``: one row per (date, conversion_action), aggregated
        across campaigns.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        normalized_limit = normalize_positive_int("limit", limit)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        meta = {
            "filters": {
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "campaign_status": campaign_status,
                "campaign_primary_status": campaign_primary_status,
            },
            "date_range": date_range.as_dict(),
            "group_level": group_level,
        }

        select_extras: list[str] = []
        if group_level == "campaign":
            select_extras.append("campaign.id, campaign.name")
        if group_level == "daily":
            select_extras.append("segments.date")
        select_extras.append(
            "segments.conversion_action, "
            "segments.conversion_action_name, "
            "segments.conversion_action_category"
        )
        select_clause = ",\n                ".join(select_extras)

        query = f"""
            SELECT
                {select_clause},
                metrics.conversions, metrics.conversions_value,
                metrics.conversions_by_conversion_date,
                metrics.conversions_value_by_conversion_date,
                metrics.all_conversions, metrics.all_conversions_value
            FROM campaign
            WHERE {where_clause}
        """

        buckets: dict[tuple, dict] = {}
        for row in search_rows(customer_id, query, login_customer_id):
            action_id = _conversion_action_id_from_resource(row.segments.conversion_action)
            action_name = row.segments.conversion_action_name
            action_category = enum_name(row.segments.conversion_action_category)
            if group_level == "campaign":
                key = (str(row.campaign.id), row.campaign.name, action_id, action_name, action_category)
            elif group_level == "daily":
                key = (str(row.segments.date), action_id, action_name, action_category)
            else:
                key = (action_id, action_name, action_category)
            bucket = buckets.setdefault(
                key,
                {
                    "conversions": 0.0,
                    "conversion_value": 0.0,
                    "conversions_by_conversion_date": 0.0,
                    "conversion_value_by_conversion_date": 0.0,
                    "all_conversions": 0.0,
                    "all_conversions_value": 0.0,
                },
            )
            bucket["conversions"] += row.metrics.conversions
            bucket["conversion_value"] += row.metrics.conversions_value
            bucket["conversions_by_conversion_date"] += row.metrics.conversions_by_conversion_date
            bucket["conversion_value_by_conversion_date"] += row.metrics.conversions_value_by_conversion_date
            bucket["all_conversions"] += row.metrics.all_conversions
            bucket["all_conversions_value"] += row.metrics.all_conversions_value

        rows_out: list[dict[str, object]] = []
        for key, bucket in buckets.items():
            row_out: dict[str, object] = {}
            if group_level == "campaign":
                row_out["campaign_id"] = key[0]
                row_out["campaign_name"] = key[1]
                row_out["conversion_action_id"] = key[2]
                row_out["conversion_action_name"] = key[3]
                row_out["conversion_action_category"] = key[4]
            elif group_level == "daily":
                row_out["date"] = key[0]
                row_out["conversion_action_id"] = key[1]
                row_out["conversion_action_name"] = key[2]
                row_out["conversion_action_category"] = key[3]
            else:
                row_out["conversion_action_id"] = key[0]
                row_out["conversion_action_name"] = key[1]
                row_out["conversion_action_category"] = key[2]
            row_out.update(bucket)
            rows_out.append(row_out)

        default_order = "date" if group_level == "daily" else "conversions"
        sort_key = _CONVERSION_AGG_SORT_KEYS.get((order_by or default_order).lower())
        if sort_key is None:
            valid = ", ".join(_CONVERSION_AGG_SORT_KEYS)
            raise ValueError(
                f"Invalid order_by '{order_by}' for conversion breakdown report. "
                f"Valid: {valid}."
            )
        rows_out.sort(key=sort_key, reverse=(sort_order.upper() != "ASC"))
        rows_out = rows_out[: normalized_limit or DEFAULT_LIMIT]

        return fmt_table(meta, rows_out)
    except Exception as exc:
        return error_response(exc)


def get_conversion_breakdown_overall(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Conversions per conversion action – aggregated across campaigns and dates.

    Use when the question is "which conversion actions drove which share of
    results", or comparing click-date (``conversions``) vs conversion-date
    (``conversions_by_conversion_date``) attribution per action. Default
    ordering: ``conversions DESC``.

    No cost/impressions/clicks – ``segments.conversion_action`` is
    incompatible with those metrics in GAQL. Use ``get_campaigns_report``
    or ``get_daily_performance`` alongside this for cost context.

    Returns per row: conversion_action_id, conversion_action_name,
    conversion_action_category, conversions, conversion_value,
    conversions_by_conversion_date, conversion_value_by_conversion_date,
    all_conversions, all_conversions_value.
    """
    return _get_conversion_breakdown(
        customer_id,
        group_level="overall",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_conversion_breakdown_by_campaign(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Conversions per (campaign, conversion action).

    Use to attribute conversions to specific campaigns per action – e.g.
    "which campaign drives purchases vs. which drives leads". Default
    ordering: ``conversions DESC``.

    No cost/impressions/clicks (see ``get_conversion_breakdown_overall``
    for the incompatibility rationale).

    Returns per row: campaign_id, campaign_name, conversion_action_id,
    conversion_action_name, conversion_action_category, and the six
    conversion metrics.
    """
    return _get_conversion_breakdown(
        customer_id,
        group_level="campaign",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_daily_conversion_breakdown(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "ASC",
) -> str:
    """Conversions per (date, conversion action) – aggregated across campaigns.

    Use to trend individual conversion actions over time – e.g. "when did
    purchases pick up vs. leads?" or to compare click-date vs
    conversion-date attribution day by day. Default ordering: ``date ASC``.

    No cost/impressions/clicks (see ``get_conversion_breakdown_overall``
    for the incompatibility rationale).

    Returns per row: date, conversion_action_id, conversion_action_name,
    conversion_action_category, and the six conversion metrics.
    """
    return _get_conversion_breakdown(
        customer_id,
        group_level="daily",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_search_terms(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Actual search queries that triggered ads, with performance.

    Use to find wasted spend (high cost, no conversions) or negative
    keyword candidates. For the keyword-to-search-term mapping, use
    `get_search_term_keyword_mapping`. Default limit: 100. Rows under
    ``REMOVED`` campaigns/ad groups are excluded by default.

    Returns per search term: search_term, status (ADDED/EXCLUDED/NONE),
    campaign_id/name, ad_group_id/name, impressions, clicks, cost,
    conversions, ctr (%), cpa.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        query = f"""
            SELECT
                search_term_view.search_term,
                search_term_view.status,
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions
            FROM search_term_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        search_terms = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            search_terms.append(
                {
                    "search_term": row.search_term_view.search_term,
                    "status": enum_name(row.search_term_view.status),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "ad_group_id": ad_group_id,
                    "ad_group_name": ad_group_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                    "ad_group_status": ad_group_status,
                    "ad_group_primary_status": ad_group_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            search_terms,
        )
    except Exception as exc:
        return error_response(exc)


def get_geo_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance broken down by geographic location (where users saw the ad).

    Use to find top/weak geos for bid adjustments or geo-targeting. Reports
    based on physical user location. Default limit: 200. REMOVED campaigns
    are excluded by default.

    Returns per geo: geo_name, canonical_name (e.g. "New York,NY,US"),
    geo_type (Country/Region/City/...), location_type (PHYSICAL/PRESENCE),
    campaign_id/name, impressions, clicks, cost, conversions,
    conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                geographic_view.country_criterion_id,
                geographic_view.location_type,
                campaign.id, campaign.name,
                geo_target_constant.name,
                geo_target_constant.canonical_name,
                geo_target_constant.target_type,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM geographic_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        geo_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            geo_performance.append(
                {
                    "geo_name": row.geo_target_constant.name,
                    "canonical_name": row.geo_target_constant.canonical_name,
                    "geo_type": row.geo_target_constant.target_type,
                    "location_type": enum_name(row.geographic_view.location_type),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            geo_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_device_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance broken down by device type (MOBILE, DESKTOP, TABLET, CONNECTED_TV).

    Use to inform device bid adjustments or diagnose why mobile/desktop
    underperforms. Each campaign appears once per device it served on.
    REMOVED campaigns are excluded by default.

    Returns per device × campaign: device, campaign_id/name, impressions,
    clicks, cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                segments.device,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        device_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            device_performance.append(
                {
                    "device": enum_name(row.segments.device),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            device_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_ad_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Ad-level creative performance (one row per ad).

    Use to compare headlines/descriptions across responsive search ads or
    find underperforming creatives. Excludes REMOVED ads and (by default)
    REMOVED parent campaigns/ad groups. Default limit: 100.

    Returns per ad: ad_id, ad_type (RESPONSIVE_SEARCH_AD, etc.), status,
    headlines (list), descriptions (list), final_urls (list),
    campaign_id/name, ad_group_id/name, impressions, clicks, cost,
    conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            "ad_group_ad.status != 'REMOVED'",
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        query = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.type,
                ad_group_ad.ad.final_urls,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.status,
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM ad_group_ad
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        ad_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            ad_performance.append(
                {
                    "ad_id": str(row.ad_group_ad.ad.id),
                    "ad_type": enum_name(row.ad_group_ad.ad.type_),
                    "status": enum_name(row.ad_group_ad.status),
                    "headlines": [headline.text for headline in row.ad_group_ad.ad.responsive_search_ad.headlines],
                    "descriptions": [
                        description.text for description in row.ad_group_ad.ad.responsive_search_ad.descriptions
                    ],
                    "final_urls": list(row.ad_group_ad.ad.final_urls),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "ad_group_id": ad_group_id,
                    "ad_group_name": ad_group_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                    "ad_group_status": ad_group_status,
                    "ad_group_primary_status": ad_group_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            ad_performance,
        )
    except Exception as exc:
        return error_response(exc)


def _get_age(
    customer_id: str,
    *,
    group_level: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Shared age-performance core.

    ``group_level`` controls output granularity:
      - ``"age"``: aggregate across all parents – one row per age_range.
      - ``"campaign"``: one row per (campaign, age_range).
      - ``"ad_group"``: per-criterion detail (no aggregation).
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        normalized_limit = normalize_positive_int("limit", limit)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        filters_meta = {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "ad_group_id": ad_group_id,
            "ad_group_name": ad_group_name,
            "campaign_status": campaign_status,
            "campaign_primary_status": campaign_primary_status,
            "ad_group_status": ad_group_status,
            "ad_group_primary_status": ad_group_primary_status,
        }
        meta = {"filters": filters_meta, "date_range": date_range.as_dict(), "group_level": group_level}

        if group_level == "ad_group":
            query = f"""
                SELECT
                    ad_group_criterion.age_range.type,
                    campaign.id, campaign.name,
                    ad_group.id, ad_group.name,
                    metrics.impressions, metrics.clicks, metrics.cost_micros,
                    metrics.conversions, metrics.conversions_value
                FROM age_range_view
                WHERE {where_clause}
                {build_order_by(order_by, sort_order)}
                {build_limit(normalized_limit or DEFAULT_LIMIT)}
            """
            rows_out = []
            for row in search_rows(customer_id, query, login_customer_id):
                cost = cost_from_micros(row.metrics.cost_micros)
                rows_out.append(
                    {
                        "age_range": enum_name(row.ad_group_criterion.age_range.type_),
                        "campaign_id": str(row.campaign.id),
                        "campaign_name": row.campaign.name,
                        "ad_group_id": str(row.ad_group.id),
                        "ad_group_name": row.ad_group.name,
                        "impressions": row.metrics.impressions,
                        "clicks": row.metrics.clicks,
                        "cost": cost,
                        "conversions": row.metrics.conversions,
                        "conversion_value": row.metrics.conversions_value,
                        "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                        "cpa": safe_divide(cost, row.metrics.conversions),
                        "roas": safe_divide(row.metrics.conversions_value, cost),
                    }
                )
            return fmt_table(meta, rows_out)

        # age / campaign → aggregate in Python (GAQL has no GROUP BY).
        if group_level == "campaign":
            select_line = "campaign.id, campaign.name,"
        else:
            select_line = ""
        query = f"""
            SELECT
                ad_group_criterion.age_range.type,
                {select_line}
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM age_range_view
            WHERE {where_clause}
        """
        buckets: dict[tuple, dict] = {}
        for row in search_rows(customer_id, query, login_customer_id):
            age_range = enum_name(row.ad_group_criterion.age_range.type_)
            if group_level == "campaign":
                key = (str(row.campaign.id), row.campaign.name, age_range)
            else:
                key = (age_range,)
            bucket = buckets.setdefault(
                key,
                {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0.0, "conversion_value": 0.0},
            )
            bucket["impressions"] += row.metrics.impressions
            bucket["clicks"] += row.metrics.clicks
            bucket["cost_micros"] += row.metrics.cost_micros
            bucket["conversions"] += row.metrics.conversions
            bucket["conversion_value"] += row.metrics.conversions_value

        rows_out = []
        for key, bucket in buckets.items():
            cost = cost_from_micros(bucket["cost_micros"])
            row_out: dict[str, object] = {}
            if group_level == "campaign":
                row_out["age_range"] = key[2]
                row_out["campaign_id"] = key[0]
                row_out["campaign_name"] = key[1]
            else:
                row_out["age_range"] = key[0]
            row_out.update(
                {
                    "impressions": bucket["impressions"],
                    "clicks": bucket["clicks"],
                    "cost": cost,
                    "conversions": bucket["conversions"],
                    "conversion_value": bucket["conversion_value"],
                    "ctr": safe_percentage(bucket["clicks"], bucket["impressions"]),
                    "cpa": safe_divide(cost, bucket["conversions"]),
                    "roas": safe_divide(bucket["conversion_value"], cost),
                }
            )
            rows_out.append(row_out)

        sort_key = _DIMENSION_AGG_SORT_KEYS.get((order_by or "impressions").lower())
        if sort_key is None:
            valid = ", ".join(_DIMENSION_AGG_SORT_KEYS)
            raise ValueError(
                f"Invalid order_by '{order_by}' for aggregated age report. Valid: {valid}."
            )
        rows_out.sort(key=sort_key, reverse=(sort_order.upper() != "ASC"))
        rows_out = rows_out[: normalized_limit or DEFAULT_LIMIT]

        return fmt_table(meta, rows_out)
    except Exception as exc:
        return error_response(exc)


def get_age_overall(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Total age-range performance summed across all campaigns and ad groups.

    One row per age_range. Use to compare demographic slices on absolute
    spend/conversions regardless of where they served. For per-campaign
    breakdown use `get_age_by_campaign`; for criterion-level detail use
    `get_age_by_ad_group`.

    REMOVED parents are excluded by default – override via
    ``campaign_status`` / ``ad_group_status``. ``order_by`` accepts
    ``impressions`` (default) / ``cost`` / ``clicks`` / ``conversions`` /
    ``conversion_value``.

    Returns per age_range: age_range, impressions, clicks, cost,
    conversions, conversion_value, ctr (%), cpa, roas.
    """
    return _get_age(
        customer_id,
        group_level="age",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_age_by_campaign(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Age-range performance broken down by parent campaign.

    One row per (campaign, age_range). Use to see which age groups perform
    where. For criterion-level detail (per ad group) use
    `get_age_by_ad_group`. Same filtering/defaults as the siblings.

    Returns per row: age_range, campaign_id, campaign_name, impressions,
    clicks, cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    return _get_age(
        customer_id,
        group_level="campaign",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_age_by_ad_group(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Per-criterion age detail: one row per (ad_group, age_range).

    Use for fine-grained demographic analysis when you need to see how a
    given age range performs inside each ad group. For aggregated views
    use `get_age_overall` or `get_age_by_campaign`.

    Returns per row: age_range, campaign_id/name, ad_group_id/name,
    impressions, clicks, cost, conversions, conversion_value, ctr (%),
    cpa, roas.
    """
    return _get_age(
        customer_id,
        group_level="ad_group",
        login_customer_id=login_customer_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        ad_group_status=ad_group_status,
        ad_group_primary_status=ad_group_primary_status,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_gender_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance broken down by gender.

    Use to inform demographic bid adjustments or identify best-converting
    gender slices. For age breakdown use `get_age_performance`.
    REMOVED campaigns/ad groups are excluded by default.

    Returns per row: gender (MALE/FEMALE/UNDETERMINED), campaign_id/name,
    impressions, clicks, cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        query = f"""
            SELECT
                ad_group_criterion.gender.type,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM gender_view
            WHERE {where_clause}
        """
        # ad_group.status in WHERE segments rows by ad_group; aggregate back to
        # (campaign, gender) in Python since GAQL has no GROUP BY.
        buckets: dict[tuple, dict] = {}
        for row in search_rows(customer_id, query, login_customer_id):
            key = (
                str(row.campaign.id),
                row.campaign.name,
                enum_name(row.ad_group_criterion.gender.type_),
            )
            bucket = buckets.setdefault(
                key,
                {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0.0, "conversion_value": 0.0},
            )
            bucket["impressions"] += row.metrics.impressions
            bucket["clicks"] += row.metrics.clicks
            bucket["cost_micros"] += row.metrics.cost_micros
            bucket["conversions"] += row.metrics.conversions
            bucket["conversion_value"] += row.metrics.conversions_value

        gender_performance = []
        for (campaign_id_, campaign_name_, gender), bucket in buckets.items():
            cost = cost_from_micros(bucket["cost_micros"])
            gender_performance.append(
                {
                    "gender": gender,
                    "campaign_id": campaign_id_,
                    "campaign_name": campaign_name_,
                    "impressions": bucket["impressions"],
                    "clicks": bucket["clicks"],
                    "cost": cost,
                    "conversions": bucket["conversions"],
                    "conversion_value": bucket["conversion_value"],
                    "ctr": safe_percentage(bucket["clicks"], bucket["impressions"]),
                    "cpa": safe_divide(cost, bucket["conversions"]),
                    "roas": safe_divide(bucket["conversion_value"], cost),
                }
            )

        sort_key = _DIMENSION_AGG_SORT_KEYS.get((order_by or "impressions").lower())
        if sort_key is None:
            valid = ", ".join(_DIMENSION_AGG_SORT_KEYS)
            raise ValueError(
                f"Invalid order_by '{order_by}' for aggregated gender report. Valid: {valid}."
            )
        gender_performance.sort(key=sort_key, reverse=(sort_order.upper() != "ASC"))
        gender_performance = gender_performance[: limit or DEFAULT_LIMIT]

        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "ad_group_id": ad_group_id,
                    "ad_group_name": ad_group_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                    "ad_group_status": ad_group_status,
                    "ad_group_primary_status": ad_group_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            gender_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_audience_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance of audience targets attached to campaigns.

    Use to evaluate in-market, custom, affinity, or remarketing audiences
    assigned at the campaign level. Default limit: 100. REMOVED campaigns
    are excluded by default.

    Returns per audience: resource_name, audience_name (display),
    audience_type (USER_INTEREST, USER_LIST, CUSTOM_AUDIENCE, ...),
    audience_status, criterion_id, campaign_id/name, impressions,
    clicks, cost, conversions, conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                campaign_audience_view.resource_name,
                campaign_criterion.criterion_id,
                campaign_criterion.display_name,
                campaign_criterion.type,
                campaign_criterion.status,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign_audience_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        audience_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            audience_performance.append(
                {
                    "resource_name": row.campaign_audience_view.resource_name,
                    "audience_name": row.campaign_criterion.display_name,
                    "audience_type": enum_name(row.campaign_criterion.type_),
                    "audience_status": enum_name(row.campaign_criterion.status),
                    "criterion_id": str(row.campaign_criterion.criterion_id),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            audience_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_hourly_performance(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance segmented by day-of-week × hour-of-day.

    Use for ad-scheduling (dayparting) decisions: identify peak/low-ROI
    windows. Default ordering: day_of_week, hour ASC. REMOVED campaigns
    are excluded by default.

    Returns per slot: day_of_week (MONDAY..SUNDAY), hour (0-23),
    campaign_id/name, impressions, clicks, cost, conversions,
    conversion_value, ctr (%), cpa, roas.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        query = f"""
            SELECT
                segments.day_of_week,
                segments.hour,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order, default="segments.day_of_week, segments.hour")}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        hourly_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            hourly_performance.append(
                {
                    "day_of_week": enum_name(row.segments.day_of_week),
                    "hour": row.segments.hour,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            hourly_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_search_term_keyword_mapping(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    ad_group_id: str | list[str] | None = None,
    ad_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
    ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Join search terms to the keywords that triggered them.

    Use when you need to know which keyword brought in a specific search
    query – e.g. to decide whether to add the term as its own keyword, or
    which keyword to refine. Default limit: 500. Rows under ``REMOVED``
    campaigns/ad groups are excluded by default.

    Returns per pair: search_term, keyword_text, match_type (EXACT/PHRASE/
    BROAD), campaign_id/name, ad_group_id/name, impressions, clicks, cost,
    conversions, ctr (%), cpa.
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("ad_group.id", ad_group_id),
            name_filter("ad_group.name", ad_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                ad_group_status=ad_group_status,
                ad_group_primary_status=ad_group_primary_status,
            ),
        )
        query = f"""
            SELECT
                search_term_view.search_term,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions
            FROM search_term_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        mapping = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            mapping.append(
                {
                    "search_term": row.search_term_view.search_term,
                    "keyword_text": row.ad_group_criterion.keyword.text,
                    "match_type": enum_name(row.ad_group_criterion.keyword.match_type),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                }
            )
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "ad_group_id": ad_group_id,
                    "ad_group_name": ad_group_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                    "ad_group_status": ad_group_status,
                    "ad_group_primary_status": ad_group_primary_status,
                },
                "date_range": date_range.as_dict(),
            },
            mapping,
        )
    except Exception as exc:
        return error_response(exc)


_ASSET_GROUP_PERFORMANCE_LABELS = frozenset({"PENDING", "LEARNING", "LOW", "GOOD", "BEST", "UNKNOWN"})
_ASSET_GROUP_ASSET_SOURCES = frozenset({"ADVERTISER", "AUTOMATICALLY_CREATED"})
_ASSET_GROUP_ASSET_STATUSES = frozenset({"ENABLED", "PAUSED", "REMOVED"})

_IMAGE_ORIENTATION_BY_FIELD_TYPE = {
    "MARKETING_IMAGE": "Horizontal",
    "SQUARE_MARKETING_IMAGE": "Square",
    "PORTRAIT_MARKETING_IMAGE": "Vertical",
    "LOGO": "Logo",
    "LANDSCAPE_LOGO": "Landscape Logo",
}


def _asset_group_field_type_clause(field_types: list[str], override: str | list[str] | None) -> str:
    """Build the asset_group_asset.field_type clause.

    ``field_types`` is the tool's canonical set; ``override`` optionally
    narrows it (validated to be a subset).
    """
    if override is None:
        values = field_types
    else:
        raw = [override] if isinstance(override, str) else list(override)
        cleaned = [str(v).strip().upper() for v in raw if v and str(v).strip()]
        invalid = [v for v in cleaned if v not in field_types]
        if invalid:
            raise ValueError(
                f"Invalid field_type value(s): {invalid}. Allowed: {sorted(field_types)}"
            )
        values = cleaned or field_types
    if len(values) == 1:
        return f"asset_group_asset.field_type = '{values[0]}'"
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"asset_group_asset.field_type IN ({quoted})"


def _get_asset_group_assets(
    customer_id: str,
    *,
    login_customer_id: str | None = None,
    field_types: list[str],
    extra_select: list[str],
    row_extractor,
    campaign_id: str | list[str] | None,
    campaign_name: str | list[str] | None,
    asset_group_id: str | list[str] | None,
    asset_group_name: str | list[str] | None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None,
    asset_group_status: AssetGroupStatus | list[AssetGroupStatus] | None,
    asset_group_primary_status: AssetGroupPrimaryStatus | list[AssetGroupPrimaryStatus] | None,
    performance_label: str | list[str] | None,
    source: str | list[str] | None,
    status: AssetGroupStatus | list[AssetGroupStatus] | None,
    field_type: str | list[str] | None,
    date_range_days: int | None,
    date_from: str | None,
    date_to: str | None,
    limit: int | None,
    order_by: str | None,
    sort_order: SortOrder,
) -> str:
    """Shared asset_group_asset reporting core.

    ``field_types`` is the canonical set the tool operates over; ``field_type``
    is the caller-supplied narrowing filter. ``extra_select`` adds asset.*
    fields to the SELECT list, and ``row_extractor`` returns per-type columns
    from a proto row (e.g. {"text": ...} or {"image_url": ..., "width": ...}).
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            date_range.clause,
            _asset_group_field_type_clause(field_types, field_type),
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            id_filter("asset_group.id", asset_group_id),
            name_filter("asset_group.name", asset_group_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                asset_group_status=asset_group_status,
                asset_group_primary_status=asset_group_primary_status,
                apply_ad_group=False,
                apply_asset_group=True,
            ),
            enum_filter("asset_group_asset.status", status, _ASSET_GROUP_ASSET_STATUSES)
            if status is not None
            else "asset_group_asset.status != 'REMOVED'",
            enum_filter("asset_group_asset.performance_label", performance_label, _ASSET_GROUP_PERFORMANCE_LABELS),
            enum_filter("asset_group_asset.source", source, _ASSET_GROUP_ASSET_SOURCES),
        )
        select_extra = ",\n                ".join(extra_select)
        query = f"""
            SELECT
                campaign.id, campaign.name, campaign.advertising_channel_type,
                asset_group.id, asset_group.name,
                asset_group_asset.field_type,
                asset_group_asset.status,
                asset_group_asset.performance_label,
                asset_group_asset.source,
                asset_group_asset.primary_status,
                asset_group_asset.primary_status_reasons,
                asset_group_asset.policy_summary.approval_status,
                asset.id,
                {select_extra},
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
            FROM asset_group_asset
            WHERE {where_clause}
            {build_order_by(order_by, sort_order, default="metrics.impressions DESC")}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        rows_out = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            row_out = {
                "campaign_id": str(row.campaign.id),
                "campaign_name": row.campaign.name,
                "campaign_type": enum_name(row.campaign.advertising_channel_type),
                "asset_group_id": str(row.asset_group.id),
                "asset_group_name": row.asset_group.name,
                "asset_id": str(row.asset.id),
                "field_type": enum_name(row.asset_group_asset.field_type),
                "status": enum_name(row.asset_group_asset.status),
                "performance_label": enum_name(row.asset_group_asset.performance_label),
                "source": enum_name(row.asset_group_asset.source),
                "primary_status": enum_name(row.asset_group_asset.primary_status),
                "primary_status_reasons": [
                    enum_name(r) for r in row.asset_group_asset.primary_status_reasons
                ],
                "approval_status": enum_name(row.asset_group_asset.policy_summary.approval_status),
            }
            row_out.update(row_extractor(row))
            row_out.update(
                {
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
                    "cpa": safe_divide(cost, row.metrics.conversions),
                    "roas": safe_divide(row.metrics.conversions_value, cost),
                }
            )
            rows_out.append(row_out)
        return fmt_table(
            {
                "filters": {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "asset_group_id": asset_group_id,
                    "asset_group_name": asset_group_name,
                    "campaign_status": campaign_status,
                    "campaign_primary_status": campaign_primary_status,
                    "asset_group_status": asset_group_status,
                    "asset_group_primary_status": asset_group_primary_status,
                    "performance_label": performance_label,
                    "source": source,
                    "status": status,
                    "field_type": field_type,
                },
                "date_range": date_range.as_dict(),
            },
            rows_out,
        )
    except Exception as exc:
        return error_response(exc)


def get_asset_group_text_assets(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    asset_group_id: str | list[str] | None = None,
    asset_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    asset_group_status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    asset_group_primary_status: AssetGroupPrimaryStatus | list[AssetGroupPrimaryStatus] | None = None,
    performance_label: str | list[str] | None = None,
    source: str | list[str] | None = None,
    status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    field_type: str | list[str] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance Max text creative assets (headlines, long headlines, descriptions).

    Queries `asset_group_asset` for `HEADLINE` / `LONG_HEADLINE` /
    `DESCRIPTION` field types. Use to audit PMax text creatives and triage
    `performance_label` ratings (PENDING/LEARNING/LOW/GOOD/BEST).

    Args:
        performance_label: filter on Google's per-asset rating. One of
            PENDING, LEARNING, LOW, GOOD, BEST, UNKNOWN, or a list.
        source: ADVERTISER or AUTOMATICALLY_CREATED – filters to caller-
            uploaded vs Google-generated creatives.
        field_type: narrow to a subset of {HEADLINE, LONG_HEADLINE,
            DESCRIPTION}.

    Returns per row: campaign_id/name/type, asset_group_id/name, asset_id,
    field_type, text, status, performance_label, source, primary_status,
    primary_status_reasons, approval_status, impressions, clicks, cost,
    conversions, conversion_value, ctr (%), cpa, roas.
    """
    return _get_asset_group_assets(
        customer_id,
        login_customer_id=login_customer_id,
        field_types=["HEADLINE", "LONG_HEADLINE", "DESCRIPTION"],
        extra_select=["asset.text_asset.text"],
        row_extractor=lambda row: {"text": row.asset.text_asset.text},
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        asset_group_id=asset_group_id,
        asset_group_name=asset_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        asset_group_status=asset_group_status,
        asset_group_primary_status=asset_group_primary_status,
        performance_label=performance_label,
        source=source,
        status=status,
        field_type=field_type,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_asset_group_video_assets(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    asset_group_id: str | list[str] | None = None,
    asset_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    asset_group_status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    asset_group_primary_status: AssetGroupPrimaryStatus | list[AssetGroupPrimaryStatus] | None = None,
    performance_label: str | list[str] | None = None,
    source: str | list[str] | None = None,
    status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance Max YouTube video creative assets.

    Queries `asset_group_asset` for `YOUTUBE_VIDEO` field type. Use to
    audit PMax video creatives and see which are performing vs flagged
    LOW. Includes a derived `youtube_url` column for easy previewing.

    Returns per row: campaign_id/name/type, asset_group_id/name, asset_id,
    field_type, youtube_video_id, youtube_video_title, youtube_url,
    status, performance_label, source, primary_status,
    primary_status_reasons, approval_status, impressions, clicks, cost,
    conversions, conversion_value, ctr (%), cpa, roas.
    """

    def extract(row) -> dict[str, object]:
        video_id = row.asset.youtube_video_asset.youtube_video_id
        return {
            "youtube_video_id": video_id,
            "youtube_video_title": row.asset.youtube_video_asset.youtube_video_title,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        }

    return _get_asset_group_assets(
        customer_id,
        login_customer_id=login_customer_id,
        field_types=["YOUTUBE_VIDEO"],
        extra_select=[
            "asset.youtube_video_asset.youtube_video_id",
            "asset.youtube_video_asset.youtube_video_title",
        ],
        row_extractor=extract,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        asset_group_id=asset_group_id,
        asset_group_name=asset_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        asset_group_status=asset_group_status,
        asset_group_primary_status=asset_group_primary_status,
        performance_label=performance_label,
        source=source,
        status=status,
        field_type=None,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


def get_asset_group_image_assets(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    asset_group_id: str | list[str] | None = None,
    asset_group_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
    asset_group_status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    asset_group_primary_status: AssetGroupPrimaryStatus | list[AssetGroupPrimaryStatus] | None = None,
    performance_label: str | list[str] | None = None,
    source: str | list[str] | None = None,
    status: AssetGroupStatus | list[AssetGroupStatus] | None = None,
    field_type: str | list[str] | None = None,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Performance Max image creative assets (marketing images + logos).

    Queries `asset_group_asset` for MARKETING_IMAGE, SQUARE_MARKETING_IMAGE,
    PORTRAIT_MARKETING_IMAGE, LOGO, LANDSCAPE_LOGO field types. Use to
    audit PMax image creatives by dimension; the `orientation` column
    labels each row (Horizontal / Square / Vertical / Logo / Landscape
    Logo).

    Args:
        field_type: narrow to a subset of {MARKETING_IMAGE,
            SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, LOGO,
            LANDSCAPE_LOGO}.

    Returns per row: campaign_id/name/type, asset_group_id/name, asset_id,
    field_type, orientation, image_url, width, height, file_size,
    mime_type, status, performance_label, source, primary_status,
    primary_status_reasons, approval_status, impressions, clicks, cost,
    conversions, conversion_value, ctr (%), cpa, roas.
    """

    def extract(row) -> dict[str, object]:
        full = row.asset.image_asset.full_size
        return {
            "orientation": _IMAGE_ORIENTATION_BY_FIELD_TYPE.get(
                enum_name(row.asset_group_asset.field_type), ""
            ),
            "image_url": full.url,
            "width": full.width_pixels,
            "height": full.height_pixels,
            "file_size": row.asset.image_asset.file_size,
            "mime_type": enum_name(row.asset.image_asset.mime_type),
        }

    return _get_asset_group_assets(
        customer_id,
        login_customer_id=login_customer_id,
        field_types=[
            "MARKETING_IMAGE",
            "SQUARE_MARKETING_IMAGE",
            "PORTRAIT_MARKETING_IMAGE",
            "LOGO",
            "LANDSCAPE_LOGO",
        ],
        extra_select=[
            "asset.image_asset.full_size.url",
            "asset.image_asset.full_size.width_pixels",
            "asset.image_asset.full_size.height_pixels",
            "asset.image_asset.file_size",
            "asset.image_asset.mime_type",
        ],
        row_extractor=extract,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        asset_group_id=asset_group_id,
        asset_group_name=asset_group_name,
        campaign_status=campaign_status,
        campaign_primary_status=campaign_primary_status,
        asset_group_status=asset_group_status,
        asset_group_primary_status=asset_group_primary_status,
        performance_label=performance_label,
        source=source,
        status=status,
        field_type=field_type,
        date_range_days=date_range_days,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        order_by=order_by,
        sort_order=sort_order,
    )


TOOLS = (
    get_campaigns_report,
    get_ad_groups_report,
    get_keywords_overall,
    get_keywords_by_campaign,
    get_keywords_by_ad_group,
    get_daily_performance,
    get_daily_performance_by_campaign,
    get_conversion_breakdown_overall,
    get_conversion_breakdown_by_campaign,
    get_daily_conversion_breakdown,
    get_search_terms,
    get_geo_performance,
    get_device_performance,
    get_ad_performance,
    get_age_overall,
    get_age_by_campaign,
    get_age_by_ad_group,
    get_gender_performance,
    get_audience_performance,
    get_hourly_performance,
    get_search_term_keyword_mapping,
    get_asset_group_text_assets,
    get_asset_group_video_assets,
    get_asset_group_image_assets,
)


def register(mcp: FastMCP) -> None:
    """Register core reporting tools."""
    from google_ads_mcp.observability import log_tool_call

    for fn in TOOLS:
        mcp.tool()(log_tool_call(fn))
