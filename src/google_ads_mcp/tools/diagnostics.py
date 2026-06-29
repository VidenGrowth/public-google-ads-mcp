"""Diagnostics, pacing, and audit-oriented tools."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastmcp import FastMCP

from google_ads_mcp.google_ads.client import search_rows
from google_ads_mcp.google_ads.utils import (
    AdGroupPrimaryStatus,
    AdGroupStatus,
    CampaignPrimaryStatus,
    CampaignStatus,
    SortOrder,
    asset_payload,
    build_date_clause,
    build_limit,
    build_order_by,
    build_where,
    cost_from_micros,
    enum_name,
    error_response,
    fmt,
    fmt_table,
    id_filter,
    message_to_string,
    name_filter,
    normalize_positive_int,
    safe_divide,
    safe_percentage,
    status_clauses,
    today_month_context,
)
from google_ads_mcp.tools.constants import DEFAULT_LIMIT


def get_keyword_quality_details(
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
    min_impressions: int = 0,
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    sort_order: SortOrder = "DESC",
) -> str:
    """Quality Score breakdown per keyword: expected CTR, ad relevance, landing page.

    Use to diagnose which keywords suffer from low Quality Score and why.
    Excludes REMOVED and negative keywords, plus (by default) rows under
    REMOVED campaigns/ad groups. Default ordering: quality_score ASC
    (worst first) so problem keywords surface at the top.

    Extra args:
        min_impressions: Filter out keywords with fewer impressions (default 0).
            Raise to exclude low-volume noise, e.g. 100.

    Returns per keyword: campaign_id/name, ad_group_id/name, keyword_text,
    match_type, status, quality_score (1-10), expected_ctr / ad_relevance /
    landing_page_experience (BELOW_AVERAGE / AVERAGE / ABOVE_AVERAGE),
    impressions, clicks, cost, conversions, average_cpc, ctr (%), cpa.
    """
    try:
        if min_impressions < 0:
            raise ValueError("min_impressions must be 0 or greater.")
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            "ad_group_criterion.status != 'REMOVED'",
            "ad_group_criterion.negative = FALSE",
            f"metrics.impressions >= {min_impressions}",
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
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.creative_quality_score,
                ad_group_criterion.quality_info.post_click_quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
                ad_group.id, ad_group.name,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.average_cpc
            FROM keyword_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order, default="ad_group_criterion.quality_info.quality_score ASC")}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        keyword_quality_details = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            keyword_quality_details.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "keyword_text": row.ad_group_criterion.keyword.text,
                    "match_type": enum_name(row.ad_group_criterion.keyword.match_type),
                    "status": enum_name(row.ad_group_criterion.status),
                    "quality_score": row.ad_group_criterion.quality_info.quality_score,
                    "expected_ctr": enum_name(row.ad_group_criterion.quality_info.search_predicted_ctr),
                    "ad_relevance": enum_name(row.ad_group_criterion.quality_info.creative_quality_score),
                    "landing_page_experience": enum_name(
                        row.ad_group_criterion.quality_info.post_click_quality_score
                    ),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "average_cpc": cost_from_micros(row.metrics.average_cpc),
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
                    "min_impressions": min_impressions,
                },
                "date_range": date_range.as_dict(),
            },
            keyword_quality_details,
        )
    except Exception as exc:
        return error_response(exc)


def get_ad_extensions(
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
) -> str:
    """Performance of ad extensions (sitelinks, callouts, structured snippets) at both scopes.

    Use to find which extensions drive the most clicks, or which should be
    paused. Returns two tables: `campaign_assets` (extensions attached to
    specific campaigns) and `account_assets` (account-wide extensions).
    Excludes REMOVED assets, and campaign-scoped rows under REMOVED
    campaigns are excluded by default.

    Common row fields: scope ("campaign"/"account"), asset_id, asset_name,
    asset_type (SITELINK/CALLOUT/STRUCTURED_SNIPPET/...), field_type, status,
    link_text, description1, description2, callout_text,
    structured_snippet_header, structured_snippet_values, impressions, clicks.
    Campaign rows also include campaign_id/name, cost, ctr (%).
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        limit_clause = build_limit(limit or DEFAULT_LIMIT)
        campaign_asset_where = build_where(
            "campaign_asset.status != 'REMOVED'",
            date_range.clause,
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        campaign_asset_query = f"""
            SELECT
                asset.id,
                asset.name,
                asset.type,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.sitelink_asset.link_text,
                asset.callout_asset.callout_text,
                asset.structured_snippet_asset.header,
                asset.structured_snippet_asset.values,
                campaign.id, campaign.name,
                campaign_asset.field_type,
                campaign_asset.status,
                metrics.impressions, metrics.clicks, metrics.cost_micros
            FROM campaign_asset
            WHERE {campaign_asset_where}
            ORDER BY asset.type, metrics.impressions DESC
            {limit_clause}
        """
        customer_asset_query = f"""
            SELECT
                asset.id,
                asset.name,
                asset.type,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.sitelink_asset.link_text,
                asset.callout_asset.callout_text,
                asset.structured_snippet_asset.header,
                asset.structured_snippet_asset.values,
                customer_asset.field_type,
                customer_asset.status,
                metrics.impressions, metrics.clicks
            FROM customer_asset
            WHERE {build_where("customer_asset.status != 'REMOVED'", date_range.clause)}
            ORDER BY asset.type, metrics.impressions DESC
            {limit_clause}
        """
        campaign_assets = [asset_payload(row, "campaign") for row in search_rows(customer_id, campaign_asset_query, login_customer_id)]
        account_assets = [asset_payload(row, "account") for row in search_rows(customer_id, customer_asset_query, login_customer_id)]
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
            campaign_assets=campaign_assets,
            account_assets=account_assets,
        )
    except Exception as exc:
        return error_response(exc)


def get_bid_strategies(
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
    """Bidding strategy configuration per campaign + supporting performance.

    Use to audit which campaigns use which strategy (Target CPA, Target
    ROAS, Maximize Conversions, etc.) and whether the target is being hit.
    Excludes REMOVED campaigns by default.

    Returns per campaign: campaign_id/name, status, bidding_strategy_type,
    target_cpa, maximize_conversions_target_cpa, target_roas,
    maximize_conversion_value_target_roas, daily_budget, impressions, clicks,
    cost, conversions, conversion_value, search_impression_share,
    search_budget_lost_impression_share, search_rank_lost_impression_share,
    ctr (%), cpa, roas.
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
                campaign.id, campaign.name, campaign.status,
                campaign.bidding_strategy_type,
                campaign.target_cpa.target_cpa_micros,
                campaign.target_roas.target_roas,
                campaign.maximize_conversions.target_cpa_micros,
                campaign.maximize_conversion_value.target_roas,
                campaign_budget.amount_micros,
                metrics.conversions, metrics.conversions_value,
                metrics.cost_micros, metrics.clicks, metrics.impressions,
                metrics.search_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        bid_strategies = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            bid_strategies.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": enum_name(row.campaign.status),
                    "bidding_strategy_type": enum_name(row.campaign.bidding_strategy_type),
                    "target_cpa": cost_from_micros(row.campaign.target_cpa.target_cpa_micros),
                    "maximize_conversions_target_cpa": cost_from_micros(
                        row.campaign.maximize_conversions.target_cpa_micros
                    ),
                    "target_roas": row.campaign.target_roas.target_roas,
                    "maximize_conversion_value_target_roas": row.campaign.maximize_conversion_value.target_roas,
                    "daily_budget": cost_from_micros(row.campaign_budget.amount_micros),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "search_impression_share": row.metrics.search_impression_share,
                    "search_budget_lost_impression_share": row.metrics.search_budget_lost_impression_share,
                    "search_rank_lost_impression_share": row.metrics.search_rank_lost_impression_share,
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
            bid_strategies,
        )
    except Exception as exc:
        return error_response(exc)


def get_budget_pacing(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
) -> str:
    """Month-to-date spend vs monthly budget target + end-of-month projection.

    Use to answer "are we on/over/under pace for the month?". Date range is
    fixed to current month (does not accept date_range_days/date_from/date_to).
    Only ENABLED campaigns are included.

    Returns:
      - meta: month_start, through_date (yesterday), days_elapsed,
        days_remaining, summary (account-wide totals).
      - per campaign: campaign_id/name, status, daily_budget,
        monthly_budget_target (= daily_budget × days_in_month), mtd_spend,
        avg_daily_spend, days_elapsed, days_remaining, projected_eom_spend
        (avg_daily_spend × days_in_month), needed_daily_spend_to_hit_target,
        pacing_status ("over" >5% above, "under" >5% below, "on_track",
        or "no_budget"), impressions, clicks, conversions.
    """
    try:
        month_start, yesterday, days_in_month = today_month_context()
        if yesterday < month_start:
            return fmt_table(
                {
                    "filters": {"campaign_id": campaign_id, "campaign_name": campaign_name},
                    "month_start": month_start.isoformat(),
                    "through_date": None,
                    "days_elapsed": 0,
                    "days_remaining": days_in_month,
                    "summary": {
                        "total_daily_budget": 0.0,
                        "total_monthly_budget_target": 0.0,
                        "total_mtd_spend": 0.0,
                        "projected_eom_spend": 0.0,
                        "needed_daily_spend_to_hit_target": 0.0,
                    },
                },
                [],
            )
        where_clause = build_where(
            "campaign.status = 'ENABLED'",
            f"segments.date BETWEEN '{month_start.isoformat()}' AND '{yesterday.isoformat()}'",
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
        )
        query = f"""
            SELECT
                campaign.id, campaign.name, campaign.status,
                campaign_budget.amount_micros,
                metrics.cost_micros, metrics.conversions,
                metrics.impressions, metrics.clicks
            FROM campaign
            WHERE {where_clause}
            ORDER BY metrics.cost_micros DESC
        """
        days_elapsed = (yesterday - month_start).days + 1
        days_remaining = max(days_in_month - yesterday.day, 0)
        campaign_pacing = []
        totals = {
            "total_daily_budget": 0.0,
            "total_monthly_budget_target": 0.0,
            "total_mtd_spend": 0.0,
            "projected_eom_spend": 0.0,
            "needed_daily_spend_to_hit_target": 0.0,
        }
        for row in search_rows(customer_id, query, login_customer_id):
            daily_budget = cost_from_micros(row.campaign_budget.amount_micros)
            mtd_spend = cost_from_micros(row.metrics.cost_micros)
            monthly_budget_target = round(daily_budget * days_in_month, 2)
            avg_daily_spend = safe_divide(mtd_spend, days_elapsed) or 0.0
            projected_eom_spend = round(avg_daily_spend * days_in_month, 2)
            needed_daily_spend = 0.0
            if days_remaining:
                needed_daily_spend = round(max(monthly_budget_target - mtd_spend, 0) / days_remaining, 2)
            if monthly_budget_target == 0:
                pacing_status = "no_budget"
            else:
                pacing_ratio = projected_eom_spend / monthly_budget_target
                if pacing_ratio > 1.05:
                    pacing_status = "over"
                elif pacing_ratio < 0.95:
                    pacing_status = "under"
                else:
                    pacing_status = "on_track"
            campaign_pacing.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": enum_name(row.campaign.status),
                    "daily_budget": daily_budget,
                    "monthly_budget_target": monthly_budget_target,
                    "mtd_spend": mtd_spend,
                    "avg_daily_spend": avg_daily_spend,
                    "days_elapsed": days_elapsed,
                    "days_remaining": days_remaining,
                    "projected_eom_spend": projected_eom_spend,
                    "needed_daily_spend_to_hit_target": needed_daily_spend,
                    "pacing_status": pacing_status,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "conversions": row.metrics.conversions,
                }
            )
            totals["total_daily_budget"] += daily_budget
            totals["total_monthly_budget_target"] += monthly_budget_target
            totals["total_mtd_spend"] += mtd_spend
            totals["projected_eom_spend"] += projected_eom_spend
            totals["needed_daily_spend_to_hit_target"] += needed_daily_spend
        return fmt_table({"filters": {"campaign_id": campaign_id, "campaign_name": campaign_name}, "month_start": month_start.isoformat(), "through_date": yesterday.isoformat(), "days_elapsed": days_elapsed, "days_remaining": days_remaining, "summary": {key: round(value, 2) for key, value in totals.items()}}, campaign_pacing)
    except Exception as exc:
        return error_response(exc)


def get_landing_page_performance(
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
    """Performance per landing page URL with page-quality signals.

    Use to identify underperforming destination URLs or pages with poor
    speed / mobile experience dragging down conversion rate. Default
    limit: 100. Rows under ``REMOVED`` campaigns are excluded by default.

    Returns per URL: landing_page_url (unexpanded final URL),
    campaign_id/name, impressions, clicks, cost, conversions,
    conversion_value, speed_score (1-10, higher is better),
    mobile_friendly_clicks_percentage, ctr (%), cpa, roas.
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
                landing_page_view.unexpanded_final_url,
                campaign.id, campaign.name,
                campaign.status, campaign.primary_status,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value,
                metrics.speed_score,
                metrics.mobile_friendly_clicks_percentage
            FROM landing_page_view
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        landing_page_performance = []
        for row in search_rows(customer_id, query, login_customer_id):
            cost = cost_from_micros(row.metrics.cost_micros)
            landing_page_performance.append(
                {
                    "landing_page_url": row.landing_page_view.unexpanded_final_url,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value,
                    "speed_score": row.metrics.speed_score,
                    "mobile_friendly_clicks_percentage": row.metrics.mobile_friendly_clicks_percentage,
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
            landing_page_performance,
        )
    except Exception as exc:
        return error_response(exc)


def get_change_history(customer_id: str, login_customer_id: str | None = None, date_range_days: int = 7) -> str:
    """Account change log (who changed what, when) for auditing and anomaly detection.

    Use to answer "what changed recently" – e.g. after a sudden drop in
    conversions. Hard-capped at 200 most recent events (change_event
    resource limitation).

    Args:
        date_range_days: Look back this many days (default 7). Positive integer.

    Returns per event: change_date_time, resource_type (CAMPAIGN, AD_GROUP,
    CAMPAIGN_BUDGET, ...), operation (CREATE/UPDATE/REMOVE), changed_fields
    (list of field paths), user_email, old_resource, new_resource,
    campaign_id/name (if applicable), ad_group_id/name (if applicable).
    """
    try:
        normalized_days = normalize_positive_int("date_range_days", date_range_days)
        if normalized_days is None:
            raise ValueError("date_range_days must be a positive integer")
        threshold = datetime.now() - timedelta(days=normalized_days)
        threshold_str = threshold.strftime("%Y-%m-%d %H:%M:%S")
        query = f"""
            SELECT
                change_event.change_date_time,
                change_event.change_resource_type,
                change_event.resource_change_operation,
                change_event.changed_fields,
                change_event.user_email,
                change_event.old_resource,
                change_event.new_resource,
                campaign.id, campaign.name,
                ad_group.id, ad_group.name
            FROM change_event
            WHERE change_event.change_date_time >= '{threshold_str}'
            ORDER BY change_event.change_date_time DESC
            LIMIT 200
        """
        change_history = []
        for row in search_rows(customer_id, query, login_customer_id):
            change_history.append(
                {
                    "change_date_time": str(row.change_event.change_date_time),
                    "resource_type": enum_name(row.change_event.change_resource_type),
                    "operation": enum_name(row.change_event.resource_change_operation),
                    "changed_fields": message_to_string(row.change_event.changed_fields),
                    "user_email": row.change_event.user_email,
                    "old_resource": message_to_string(row.change_event.old_resource),
                    "new_resource": message_to_string(row.change_event.new_resource),
                    "campaign_id": str(row.campaign.id) if row.campaign.id else None,
                    "campaign_name": row.campaign.name if row.campaign.name else None,
                    "ad_group_id": str(row.ad_group.id) if row.ad_group.id else None,
                    "ad_group_name": row.ad_group.name if row.ad_group.name else None,
                }
            )
        return fmt_table({"date_range_days": normalized_days}, change_history)
    except Exception as exc:
        return error_response(exc)


def get_campaign_negative_keywords(
    customer_id: str,
    login_customer_id: str | None = None,
    campaign_id: str | list[str] | None = None,
    campaign_name: str | list[str] | None = None,
    campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
    campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
) -> str:
    """Campaign-level negative keywords (exclusions). No metrics, no date range.

    Use to audit campaign exclusion lists or compare against
    `get_search_terms` to decide what to exclude next. For ad-group-level
    exclusions use `get_ad_group_negative_keywords`. Negatives under
    ``REMOVED`` campaigns are excluded by default.

    Returns per row: campaign_id, campaign_name, keyword_text, match_type,
    negative (True).
    """
    try:
        where_clause = build_where(
            "campaign_criterion.type = 'KEYWORD'",
            "campaign_criterion.negative = TRUE",
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
                campaign_criterion.keyword.text,
                campaign_criterion.keyword.match_type,
                campaign_criterion.negative,
                campaign.id, campaign.name
            FROM campaign_criterion
            WHERE {where_clause}
            ORDER BY campaign.name, campaign_criterion.keyword.text
        """
        rows_out = []
        for row in search_rows(customer_id, query, login_customer_id):
            rows_out.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "keyword_text": row.campaign_criterion.keyword.text,
                    "match_type": enum_name(row.campaign_criterion.keyword.match_type),
                    "negative": row.campaign_criterion.negative,
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
            },
            rows_out,
        )
    except Exception as exc:
        return error_response(exc)


def get_ad_group_negative_keywords(
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
) -> str:
    """Ad-group-level negative keywords (exclusions). No metrics, no date range.

    Use to audit ad-group exclusion lists. For campaign-level exclusions
    use `get_campaign_negative_keywords`. Negatives under ``REMOVED``
    parent campaigns/ad groups are excluded by default.

    Returns per row: campaign_id/name, ad_group_id/name, keyword_text,
    match_type, negative (True).
    """
    try:
        where_clause = build_where(
            "ad_group_criterion.type = 'KEYWORD'",
            "ad_group_criterion.negative = TRUE",
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
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.negative,
                ad_group.id, ad_group.name,
                campaign.id, campaign.name
            FROM ad_group_criterion
            WHERE {where_clause}
            ORDER BY campaign.name, ad_group.name, ad_group_criterion.keyword.text
        """
        rows_out = []
        for row in search_rows(customer_id, query, login_customer_id):
            rows_out.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "keyword_text": row.ad_group_criterion.keyword.text,
                    "match_type": enum_name(row.ad_group_criterion.keyword.match_type),
                    "negative": row.ad_group_criterion.negative,
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
            },
            rows_out,
        )
    except Exception as exc:
        return error_response(exc)


def get_impression_share(
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
    """Impression share diagnostics for Search campaigns.

    Use to diagnose why impressions are capped: budget-limited vs
    rank-limited, and to see share of top / absolute-top placements.
    Only SEARCH-channel campaigns are included (other channels don't
    report these metrics). REMOVED campaigns are excluded by default.

    Returns per campaign: campaign_id/name, search_impression_share,
    search_budget_lost_impression_share, search_rank_lost_impression_share,
    search_exact_match_impression_share, search_top_impression_share,
    search_absolute_top_impression_share, cost, impressions, clicks,
    ctr (%). Values are 0.0-1.0 proportions (multiply by 100 for %).
    """
    try:
        date_range = build_date_clause(date_range_days=date_range_days, date_from=date_from, date_to=date_to)
        where_clause = build_where(
            "campaign.advertising_channel_type = 'SEARCH'",
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
                campaign.id, campaign.name,
                metrics.search_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_exact_match_impression_share,
                metrics.search_top_impression_share,
                metrics.search_absolute_top_impression_share,
                metrics.cost_micros, metrics.impressions, metrics.clicks
            FROM campaign
            WHERE {where_clause}
            {build_order_by(order_by, sort_order)}
            {build_limit(limit or DEFAULT_LIMIT)}
        """
        impression_share_data = []
        for row in search_rows(customer_id, query, login_customer_id):
            impression_share_data.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "search_impression_share": row.metrics.search_impression_share,
                    "search_budget_lost_impression_share": row.metrics.search_budget_lost_impression_share,
                    "search_rank_lost_impression_share": row.metrics.search_rank_lost_impression_share,
                    "search_exact_match_impression_share": row.metrics.search_exact_match_impression_share,
                    "search_top_impression_share": row.metrics.search_top_impression_share,
                    "search_absolute_top_impression_share": row.metrics.search_absolute_top_impression_share,
                    "cost": cost_from_micros(row.metrics.cost_micros),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "ctr": safe_percentage(row.metrics.clicks, row.metrics.impressions),
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
            impression_share_data,
        )
    except Exception as exc:
        return error_response(exc)


TOOLS = (
    get_keyword_quality_details,
    get_ad_extensions,
    get_bid_strategies,
    get_budget_pacing,
    get_landing_page_performance,
    get_change_history,
    get_campaign_negative_keywords,
    get_ad_group_negative_keywords,
    get_impression_share,
)


def register(mcp: FastMCP) -> None:
    """Register diagnostics, audit, and pacing tools."""
    from google_ads_mcp.observability import log_tool_call

    for fn in TOOLS:
        mcp.tool()(log_tool_call(fn))
