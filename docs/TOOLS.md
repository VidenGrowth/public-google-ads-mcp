# Tools

The server exposes **41 read-only tools**, grouped below. Every tool takes a
`customer_id` per request and shares the same parameter conventions – date ranges,
ID/name filters, status filters, sorting. Those are documented in
[TOOLS_DESIGN.md](TOOLS_DESIGN.md).

## Account (5)
| Tool | Description |
|------|-------------|
| `get_accessible_accounts` | List accounts the credentials can reach (start here to discover `customer_id`s) |
| `get_account_info` | Core metadata for a single account (currency, timezone, tagging) |
| `get_conversion_actions` | Conversion action config + attribution settings |
| `get_campaign_labels` | Labels attached to campaigns |
| `get_ad_group_labels` | Labels attached to ad groups |

## Reporting (24)
| Tool | Description |
|------|-------------|
| `get_campaigns_report` | Campaigns with budget, health, and performance metrics |
| `get_ad_groups_report` | Ad groups with CPC bid, health, and performance metrics |
| `get_keywords_overall` | Keyword totals summed across all campaigns/ad groups |
| `get_keywords_by_campaign` | Keyword performance by parent campaign |
| `get_keywords_by_ad_group` | Per-criterion keyword detail per ad group |
| `get_daily_performance` | Daily totals across the account (one row per day) |
| `get_daily_performance_by_campaign` | Daily performance per campaign |
| `get_conversion_breakdown_overall` | Conversions per conversion action |
| `get_conversion_breakdown_by_campaign` | Conversions per (campaign, conversion action) |
| `get_daily_conversion_breakdown` | Conversions per (date, conversion action) |
| `get_search_terms` | Actual search queries that triggered ads |
| `get_geo_performance` | Performance by geographic location |
| `get_device_performance` | Performance by device type |
| `get_ad_performance` | Ad-level creative performance |
| `get_age_overall` | Age-range totals across the account |
| `get_age_by_campaign` | Age-range performance by campaign |
| `get_age_by_ad_group` | Per-criterion age detail per ad group |
| `get_gender_performance` | Performance by gender |
| `get_audience_performance` | Audience target performance |
| `get_hourly_performance` | Day-of-week × hour-of-day performance |
| `get_search_term_keyword_mapping` | Join search terms to triggering keywords |
| `get_asset_group_text_assets` | Performance Max text assets |
| `get_asset_group_video_assets` | Performance Max video assets |
| `get_asset_group_image_assets` | Performance Max image assets |

## Diagnostics (9)
| Tool | Description |
|------|-------------|
| `get_keyword_quality_details` | Quality Score component breakdown per keyword |
| `get_ad_extensions` | Extension/asset performance (sitelinks, callouts, …) |
| `get_bid_strategies` | Bidding strategy config + supporting metrics |
| `get_budget_pacing` | Month-to-date spend vs budget + projection |
| `get_landing_page_performance` | Landing page URL performance + quality signals |
| `get_change_history` | Account change log for audit/anomaly review |
| `get_campaign_negative_keywords` | Campaign-level negative keywords |
| `get_ad_group_negative_keywords` | Ad-group-level negative keywords |
| `get_impression_share` | Search impression share + lost-share metrics |

## Query (2)
| Tool | Description |
|------|-------------|
| `run_gaql_query` | Execute a raw read-only GAQL `SELECT` |
| `gaql_search` | Structured GAQL builder (resource + fields + conditions) |

## Metadata (1)
| Tool | Description |
|------|-------------|
| `get_resource_metadata` | List selectable/filterable/sortable fields for a GAQL resource |
