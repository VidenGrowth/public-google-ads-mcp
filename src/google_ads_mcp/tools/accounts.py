"""Account-level and metadata tools."""
import asyncio

from fastmcp import FastMCP

from google_ads_mcp.google_ads.client import (
    require_client,
    search_rows,
)
from google_ads_mcp.google_ads.utils import (
    AdGroupPrimaryStatus,
    AdGroupStatus,
    CampaignPrimaryStatus,
    CampaignStatus,
    build_where,
    enum_name,
    error_response,
    fmt,
    fmt_table,
    id_filter,
    name_filter,
    status_clauses,
)


# Metadata for a single directly-accessible "seed" account.
_SEED_QUERY = """
    SELECT
        customer.id,
        customer.descriptive_name,
        customer.currency_code,
        customer.time_zone,
        customer.status,
        customer.manager
    FROM customer
    LIMIT 1
"""

# ENABLED sub-accounts at every level beneath a manager seed. Querying
# ``customer_client`` from a manager returns its whole subtree, so a single
# query per manager surfaces grandchildren too (no recursion needed).
_CHILDREN_QUERY = """
    SELECT
        customer_client.id,
        customer_client.descriptive_name,
        customer_client.currency_code,
        customer_client.time_zone,
        customer_client.status,
        customer_client.manager,
        customer_client.level
    FROM customer_client
    WHERE customer_client.status = 'ENABLED'
        AND customer_client.level > 0
    ORDER BY customer_client.descriptive_name
"""


async def get_accessible_accounts() -> str:
    """List every Google Ads account the signed-in user can reach.

    Use as the first call to discover which customer_id values are valid
    for other tools when the user doesn't provide one explicitly.

    Discovery follows Google's recommended pattern and works for both
    directly-shared leaf accounts and manager (MCC) hierarchies:
      1. ``CustomerService.ListAccessibleCustomers`` returns the "seed"
         accounts the credentials can reach directly (level 0).
      2. Each seed is enriched with its own ``SELECT FROM customer`` metadata.
      3. When a seed is a manager, its ENABLED sub-accounts at every level are
         enumerated via ``customer_client`` so the leaf accounts you actually
         run reports against are surfaced too.

    Returns per account: customer_id, name (descriptive_name), currency_code,
    time_zone, status, is_manager (bool), level (0 for seeds, deeper for
    sub-accounts) and manager_customer_id (the seed MCC a sub-account was
    found under; null for seeds). When ``level > 0``, pass that
    manager_customer_id as ``login_customer_id`` to other tools.
    """
    try:
        return await _discover_accounts()
    except Exception as exc:
        return error_response(exc)


def _list_seed_ids() -> list[str]:
    """Return the customer IDs the credentials can reach directly."""
    client = require_client()
    customer_service = client.get_service("CustomerService")
    resource_names = customer_service.list_accessible_customers().resource_names
    return [resource_name.split("/")[-1] for resource_name in resource_names]


async def _discover_accounts() -> str:
    # search_rows / list_accessible_customers are blocking gRPC calls and the
    # google-ads SDK has no async client, so every API call is offloaded to a
    # worker thread via asyncio.to_thread (which copies the current context, so
    # the forwarded OAuth token survives the hop). Independent calls are then
    # awaited together with asyncio.gather instead of run one-at-a-time.
    seed_ids = await asyncio.to_thread(_list_seed_ids)

    accounts: dict[str, dict] = {}
    manager_seeds: list[str] = []
    skipped = 0

    # Pass 1: fetch every seed's own metadata concurrently. Each seed is a
    # directly-accessible account at level 0.
    seed_rows = await asyncio.gather(
        *(asyncio.to_thread(search_rows, seed_id, _SEED_QUERY) for seed_id in seed_ids),
        return_exceptions=True,
    )
    for rows in seed_rows:
        if isinstance(rows, BaseException) or not rows:
            skipped += 1
            continue
        customer = rows[0].customer
        accounts[str(customer.id)] = {
            "customer_id": str(customer.id),
            "name": customer.descriptive_name,
            "currency_code": customer.currency_code,
            "time_zone": customer.time_zone,
            "status": enum_name(customer.status),
            "is_manager": customer.manager,
            "level": 0,
            "manager_customer_id": None,
        }
        if customer.manager:
            manager_seeds.append(str(customer.id))

    # Pass 2: expand each manager seed into its ENABLED sub-accounts, again
    # concurrently. Results are merged in seed order, so dedup precedence stays
    # deterministic regardless of which query finishes first; seeds from pass 1
    # keep their level-0 identity (setdefault never overwrites them).
    child_rows_per_manager = await asyncio.gather(
        *(asyncio.to_thread(search_rows, manager_id, _CHILDREN_QUERY) for manager_id in manager_seeds),
        return_exceptions=True,
    )
    for manager_id, child_rows in zip(manager_seeds, child_rows_per_manager):
        if isinstance(child_rows, BaseException):
            skipped += 1
            continue
        for child_row in child_rows:
            client_account = child_row.customer_client
            accounts.setdefault(
                str(client_account.id),
                {
                    "customer_id": str(client_account.id),
                    "name": client_account.descriptive_name,
                    "currency_code": client_account.currency_code,
                    "time_zone": client_account.time_zone,
                    "status": enum_name(client_account.status),
                    "is_manager": client_account.manager,
                    "level": client_account.level,
                    "manager_customer_id": manager_id,
                },
            )

    ordered = sorted(
        accounts.values(),
        key=lambda a: (a["level"], (a.get("name") or "").lower()),
    )
    meta: dict = {
        "seed_accounts": len(seed_ids),
        "returned": len(ordered),
    }
    if skipped:
        meta["skipped_inaccessible"] = skipped
    return fmt_table(meta, ordered)


def get_account_info(customer_id: str,
    login_customer_id: str | None = None) -> str:
    """Core metadata for a single Google Ads account.

    Use to confirm account currency/timezone before interpreting cost or
    time-of-day reports, or to check tagging/tracking configuration.

    Returns a single object: customer_id, name, currency_code, time_zone,
    auto_tagging_enabled (bool), tracking_url_template,
    has_partners_badge (bool), is_manager (bool).
    """
    try:
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone,
                customer.auto_tagging_enabled,
                customer.tracking_url_template,
                customer.has_partners_badge,
                customer.manager
            FROM customer
            LIMIT 1
        """
        rows = search_rows(customer_id, query, login_customer_id)
        if not rows:
            return fmt({"customer_id": customer_id, "account": None})
        row = rows[0]
        return fmt(
            {
                "customer_id": customer_id,
                "account": {
                    "customer_id": str(row.customer.id),
                    "name": row.customer.descriptive_name,
                    "currency_code": row.customer.currency_code,
                    "time_zone": row.customer.time_zone,
                    "auto_tagging_enabled": row.customer.auto_tagging_enabled,
                    "tracking_url_template": row.customer.tracking_url_template,
                    "has_partners_badge": row.customer.has_partners_badge,
                    "is_manager": row.customer.manager,
                },
            }
        )
    except Exception as exc:
        return error_response(exc)


def get_conversion_actions(customer_id: str,
    login_customer_id: str | None = None) -> str:
    """Configured conversion actions with attribution and value settings.

    Use to understand which conversions are tracked, whether they count
    once or many, and which attribution model is applied. Excludes HIDDEN
    conversions. No date range (this is configuration data).

    Returns per conversion action: conversion_action_id, name, category
    (e.g. PURCHASE/LEAD/SIGN_UP), type (e.g. WEBPAGE/UPLOAD_CALLS), status
    (ENABLED/REMOVED/PAUSED), counting_type (ONE_PER_CLICK/MANY_PER_CLICK),
    default_value, always_use_default_value (bool), attribution_model
    (LAST_CLICK/DATA_DRIVEN/LINEAR/...), data_driven_model_status.
    """
    try:
        query = """
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.category,
                conversion_action.type,
                conversion_action.status,
                conversion_action.counting_type,
                conversion_action.value_settings.default_value,
                conversion_action.value_settings.always_use_default_value,
                conversion_action.attribution_model_settings.attribution_model,
                conversion_action.attribution_model_settings.data_driven_model_status
            FROM conversion_action
            WHERE conversion_action.status != 'HIDDEN'
            ORDER BY conversion_action.name
        """
        conversion_actions = []
        for row in search_rows(customer_id, query, login_customer_id):
            conversion_actions.append(
                {
                    "conversion_action_id": str(row.conversion_action.id),
                    "name": row.conversion_action.name,
                    "category": enum_name(row.conversion_action.category),
                    "type": enum_name(row.conversion_action.type_),
                    "status": enum_name(row.conversion_action.status),
                    "counting_type": enum_name(row.conversion_action.counting_type),
                    "default_value": row.conversion_action.value_settings.default_value,
                    "always_use_default_value": row.conversion_action.value_settings.always_use_default_value,
                    "attribution_model": enum_name(
                        row.conversion_action.attribution_model_settings.attribution_model
                    ),
                    "data_driven_model_status": enum_name(
                        row.conversion_action.attribution_model_settings.data_driven_model_status
                    ),
                }
            )
        return fmt_table({}, conversion_actions)
    except Exception as exc:
        return error_response(exc)


def get_campaign_labels(
        customer_id: str,
        login_customer_id: str | None = None,
        campaign_id: str | list[str] | None = None,
        campaign_name: str | list[str] | None = None,
        campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
        campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None) -> str:
    """Labels attached to campaigns.

    Use to group campaigns by tag (e.g. "Holiday2026", "Brand", "Test") or
    to discover existing labeling conventions. No metrics, no date range.
    Labels under ``REMOVED`` campaigns are excluded by default.

    Returns per row: campaign_id, campaign_name, label_id, label_name.
    """
    try:
        where_clause = build_where(
            id_filter("campaign.id", campaign_id),
            name_filter("campaign.name", campaign_name),
            *status_clauses(
                campaign_status=campaign_status,
                campaign_primary_status=campaign_primary_status,
                apply_ad_group=False,
            ),
        )
        campaign_query = f"""
            SELECT
                campaign.id, campaign.name,
                label.id, label.name
            FROM campaign_label
            WHERE {where_clause}
            ORDER BY campaign.name, label.name
        """
        campaign_labels = []
        for row in search_rows(customer_id, campaign_query, login_customer_id):
            campaign_labels.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "label_id": str(row.label.id),
                    "label_name": row.label.name,
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
            campaign_labels,
        )
    except Exception as exc:
        return error_response(exc)


def get_ad_group_labels(
        customer_id: str,
        login_customer_id: str | None = None,
        campaign_id: str | list[str] | None = None,
        campaign_name: str | list[str] | None = None,
        ad_group_id: str | list[str] | None = None,
        ad_group_name: str | list[str] | None = None,
        campaign_status: CampaignStatus | list[CampaignStatus] | None = None,
        campaign_primary_status: CampaignPrimaryStatus | list[CampaignPrimaryStatus] | None = None,
        ad_group_status: AdGroupStatus | list[AdGroupStatus] | None = None,
        ad_group_primary_status: AdGroupPrimaryStatus | list[AdGroupPrimaryStatus] | None = None) -> str:
    """Labels attached to ad groups.

    Use to group ad groups by tag (e.g. "Holiday2026", "Brand", "Test") or
    to discover existing labeling conventions. No metrics, no date range.
    Labels under ``REMOVED`` campaigns/ad groups are excluded by default.

    Returns per row: campaign_id, campaign_name, ad_group_id, ad_group_name,
    label_id, label_name.
    """
    try:
        where_clause = build_where(
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
        ad_group_query = f"""
            SELECT
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                label.id, label.name
            FROM ad_group_label
            WHERE {where_clause}
            ORDER BY campaign.name, ad_group.name, label.name
        """
        ad_group_labels = []
        for row in search_rows(customer_id, ad_group_query, login_customer_id):
            ad_group_labels.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "label_id": str(row.label.id),
                    "label_name": row.label.name,
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
            ad_group_labels,
        )
    except Exception as exc:
        return error_response(exc)


TOOLS = (
    get_accessible_accounts,
    get_account_info,
    get_conversion_actions,
    get_campaign_labels,
    get_ad_group_labels,
)


def register(mcp: FastMCP) -> None:
    """Register account and metadata tools."""
    from google_ads_mcp.observability import log_tool_call

    for fn in TOOLS:
        mcp.tool()(log_tool_call(fn))
