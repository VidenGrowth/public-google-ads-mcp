# MCP Tools Design – Google Ads Server

Reference for every tool exposed by the server: what it does, its parameters,
and the GAQL query it issues. For the runtime conventions that apply to every
tool (date handling, filters, output format) see the sections below.

---

## Common Parameter Conventions

All reporting/diagnostic tools share these conventions. Per-tool sections only
document what's unique to that tool.

- **`customer_id`** (required): Google Ads customer ID, with or without dashes
  (e.g. `"123-456-7890"` or `"1234567890"`).
- **`campaign_id` / `ad_group_id`**: single numeric string or list of strings.
  Digits only; a list produces an `IN (...)` filter.
- **`campaign_name` / `ad_group_name`**: case-insensitive substring match.
  Single string matches names containing it; a list matches names containing
  ANY of the values. Exact names are not required.
- **Status filters** (where applicable):
  - `status` / `primary_status` – entity-at-hand status (used on
    `get_campaigns_report` and `get_ad_groups_report`).
  - `campaign_status` / `campaign_primary_status` – parent campaign status.
  - `ad_group_status` / `ad_group_primary_status` – parent ad group status.
  - User-state values: `ENABLED`, `PAUSED`, `REMOVED`.
  - Primary-state values: `ELIGIBLE`, `PAUSED`, `REMOVED`, `ENDED`, `PENDING`,
    `MISCONFIGURED`, `LIMITED`, `LEARNING`, `NOT_ELIGIBLE`.
  - By default `REMOVED` rows are excluded; pass `REMOVED` explicitly to include.
- **Date range** (mutually exclusive; omit both → `LAST_30_DAYS`):
  - `date_range_days`: int, last N days ending yesterday (inclusive).
  - `date_from` + `date_to`: ISO `YYYY-MM-DD` (both required together, inclusive).
- **`limit`**: int, max rows. Omit to apply the server-wide default
  `DEFAULT_LIMIT = 5000` (set in [tools/constants.py](src/google_ads_mcp/tools/constants.py))
  – applied uniformly to every tool that issues a GAQL `LIMIT`. The only
  exception is `get_change_history`, which is hard-capped at 200 by the
  Google Ads API.
- **`order_by`**: one of `cost`, `impressions`, `clicks`, `conversions`,
  `conversion_value`. Omit for the tool's default ordering.
- **`sort_order`**: `ASC` or `DESC` (default `DESC`).

## Output Format

Tools return an XML-tagged envelope: a `<meta>` JSON block followed by a
`<data>` block wrapping a TSV grid (header line, then one row per line):

```
<meta>{"applied":{"filters":{...},"date_range":{"preset":"LAST_30_DAYS"},"row_count":42}}</meta>
<data>
campaign_id	campaign_name	status	cost	...
123	Brand – US	ENABLED	1234.56	...
</data>
```

Multi-table responses emit one `<table name="...">` block per section (e.g.
`<table name="age">`, `<table name="gender">`) instead of a single `<data>`.
Errors come back as `<error>{"error":"..."}</error>`. Cost values are converted
from micros to the account currency.

---

## Account Basics

### `get_accessible_accounts`
List every account the signed-in user can reach. Discovery follows Google's
recommended pattern and works for both directly-shared leaf accounts and
manager (MCC) hierarchies, so it needs no configured `GOOGLE_ADS_LOGIN_CUSTOMER_ID`:

1. `CustomerService.ListAccessibleCustomers` returns the "seed" accounts the
   credentials reach directly (level 0).
2. Each seed is enriched with its own `SELECT FROM customer` metadata.
3. When a seed is a manager, its ENABLED sub-accounts at every level are
   enumerated via `customer_client` (one query per manager returns the whole
   subtree).

Sub-accounts carry `manager_customer_id` (the seed MCC) so callers know which
`login_customer_id` to pass to other tools.

**Parameters:** none.

Per seed (level 0):

```sql
SELECT
    customer.id,
    customer.descriptive_name,
    customer.currency_code,
    customer.time_zone,
    customer.status,
    customer.manager
FROM customer
LIMIT 1
```

Per manager seed, to enumerate its subtree:

```sql
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
```

---

### `get_account_info`
Core metadata for a single account.

**Parameters:** `customer_id`.

```sql
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
```

---

### `get_conversion_actions`
All configured conversion actions (id, name, category, type, status, counting,
value/attribution settings).

**Parameters:** `customer_id`.

```sql
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
```

---

### `get_campaign_labels`
Labels attached to campaigns.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`.

```sql
SELECT
    campaign.id, campaign.name,
    label.id, label.name
FROM campaign_label
WHERE {campaign_filters}
```

---

### `get_ad_group_labels`
Labels attached to ad groups.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, plus campaign/ad-group status filters.

```sql
SELECT
    campaign.id, campaign.name,
    ad_group.id, ad_group.name,
    label.id, label.name
FROM ad_group_label
WHERE {filters}
```

---

## Campaign & Ad Group Reports

### `get_campaigns_report`
Campaigns with budget, health, and performance.

**Parameters:** `customer_id`, `campaign_name`, `status`, `primary_status`,
date range, `limit`, `order_by`, `sort_order`.

Returns: `campaign_id`, `campaign_name`, `status`, `primary_status`,
`primary_status_reasons`, `end_date`, `type`, `daily_budget`, `impressions`,
`clicks`, `cost`, `conversions`, `conversion_value`, `ctr`, `cpa`, `roas`.

```sql
SELECT
    campaign.id, campaign.name,
    campaign.status, campaign.primary_status, campaign.primary_status_reasons,
    campaign.end_date_time,
    campaign.advertising_channel_type,
    campaign_budget.amount_micros,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM campaign
WHERE {filters}
```

---

### `get_ad_groups_report`
Ad groups with campaign context, health, and performance.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_name`,
`status`, `primary_status`, `campaign_status`, `campaign_primary_status`,
date range, `limit`, `order_by`, `sort_order`.

```sql
SELECT
    ad_group.id, ad_group.name, ad_group.status, ad_group.primary_status,
    ad_group.primary_status_reasons,
    campaign.id, campaign.name, campaign.status, campaign.primary_status,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM ad_group
WHERE {filters}
```

---

### `get_keywords_overall` / `get_keywords_by_campaign` / `get_keywords_by_ad_group`
Keyword-level performance aggregated at three grains:

- `get_keywords_overall` – single row per keyword text+match.
- `get_keywords_by_campaign` – per keyword within each campaign.
- `get_keywords_by_ad_group` – per keyword within each ad group (finest grain).

**Parameters (all three):** `customer_id`, `campaign_id`, `campaign_name`,
`ad_group_id`, `ad_group_name`, campaign/ad-group status filters, date range,
`limit`, `order_by`, `sort_order`.

Each queries `keyword_view` and aggregates/groups accordingly:
```sql
SELECT
    ad_group_criterion.keyword.text,
    ad_group_criterion.keyword.match_type,
    campaign.id, campaign.name,      -- by_campaign / by_ad_group
    ad_group.id, ad_group.name,      -- by_ad_group only
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM keyword_view
WHERE {filters}
```

---

### `get_daily_performance`
Day-by-day totals across the account – one row per day, aggregated across
campaigns (trend/seasonality, week-over-week).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`. Campaign filters narrow the set that's aggregated but the
output has no campaign split.

```sql
SELECT
    segments.date,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM campaign
WHERE {filters}
-- rows aggregated across campaigns in Python, sorted by date ASC
```

---

### `get_daily_performance_by_campaign`
Day-by-day totals per campaign – one row per `(date, campaign)`. Use when a
day's total isn't enough and you need to see which campaign drove it.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    segments.date,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM campaign
WHERE {filters}
ORDER BY segments.date ASC, metrics.cost_micros DESC
```

---

## Conversion Breakdowns

`segments.conversion_action` is **incompatible** with cost / impressions /
clicks metrics in GAQL, so the tools below deliberately omit those and
return only conversion metrics: `metrics.conversions`,
`metrics.conversions_value`, `metrics.conversions_by_conversion_date`,
`metrics.conversions_value_by_conversion_date`, `metrics.all_conversions`,
`metrics.all_conversions_value`. Use these alongside
`get_campaigns_report` or `get_daily_performance` when you also need spend
context.

The `*_by_conversion_date` variants attribute each event to the day the
conversion occurred (instead of the click date) – useful for reconciling
with conversion-date revenue reports.

### `get_conversion_breakdown_overall`
One row per `conversion_action`, aggregated across campaigns and dates.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`. Default order: `conversions DESC`.

```sql
SELECT
    segments.conversion_action,
    segments.conversion_action_name,
    segments.conversion_action_category,
    metrics.conversions, metrics.conversions_value,
    metrics.conversions_by_conversion_date,
    metrics.conversions_value_by_conversion_date,
    metrics.all_conversions, metrics.all_conversions_value
FROM campaign
WHERE {filters}
-- rows aggregated by conversion_action in Python
```

---

### `get_conversion_breakdown_by_campaign`
One row per `(campaign, conversion_action)`. Default order:
`conversions DESC`.

```sql
SELECT
    campaign.id, campaign.name,
    segments.conversion_action,
    segments.conversion_action_name,
    segments.conversion_action_category,
    metrics.conversions, metrics.conversions_value,
    metrics.conversions_by_conversion_date,
    metrics.conversions_value_by_conversion_date,
    metrics.all_conversions, metrics.all_conversions_value
FROM campaign
WHERE {filters}
```

---

### `get_daily_conversion_breakdown`
One row per `(date, conversion_action)`, aggregated across campaigns.
Default order: `date ASC`.

```sql
SELECT
    segments.date,
    segments.conversion_action,
    segments.conversion_action_name,
    segments.conversion_action_category,
    metrics.conversions, metrics.conversions_value,
    metrics.conversions_by_conversion_date,
    metrics.conversions_value_by_conversion_date,
    metrics.all_conversions, metrics.all_conversions_value
FROM campaign
WHERE {filters}
-- rows aggregated by (date, conversion_action) in Python
```

---

### `get_hourly_performance`
Performance segmented by `day_of_week × hour_of_day` (dayparting).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    segments.day_of_week,
    segments.hour,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM campaign
WHERE {filters}
ORDER BY segments.day_of_week, segments.hour
```

---

### `get_search_terms`
Actual search queries users typed.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, campaign/ad-group status filters, date range, `limit`,
`order_by`, `sort_order`.

```sql
SELECT
    search_term_view.search_term,
    campaign.id, campaign.name,
    ad_group.id, ad_group.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM search_term_view
WHERE {filters}
```

---

### `get_search_term_keyword_mapping`
Search terms joined to the keyword that triggered them (cannibalization).

**Parameters:** same as `get_search_terms`.

```sql
SELECT
    search_term_view.search_term,
    ad_group_criterion.keyword.text,
    ad_group_criterion.keyword.match_type,
    campaign.id, campaign.name,
    ad_group.id, ad_group.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions
FROM search_term_view
WHERE {filters}
```

---

### `get_geo_performance`
Performance by user location (`geographic_view`).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    geographic_view.country_criterion_id,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM geographic_view
WHERE {filters}
```

---

### `get_device_performance`
Performance split by device (`MOBILE`, `DESKTOP`, `TABLET`, `CONNECTED_TV`).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    segments.device,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM campaign
WHERE {filters}
```

---

### `get_ad_performance`
Ad-level creative performance.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, campaign/ad-group status filters, date range, `limit`,
`order_by`, `sort_order`.

```sql
SELECT
    ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status,
    ad_group_ad.ad.final_urls,
    ad_group.id, ad_group.name,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM ad_group_ad
WHERE {filters}
```

---

### `get_age_overall` / `get_age_by_campaign` / `get_age_by_ad_group`
Age-range performance aggregated at three grains (same pattern as the
positive-keyword split):

- `get_age_overall` – one row per `age_range`, summed across all parents.
- `get_age_by_campaign` – one row per (campaign, age_range).
- `get_age_by_ad_group` – per-criterion detail, one row per (campaign,
  ad_group, age_range).

**Parameters (all three):** `customer_id`, `campaign_id`, `campaign_name`,
`ad_group_id`, `ad_group_name`, campaign/ad-group status filters, date range,
`limit`, `order_by`, `sort_order`.

All three query `age_range_view`; `overall` and `by_campaign` aggregate in
Python (GAQL has no GROUP BY), `by_ad_group` returns raw criterion rows:
```sql
SELECT
    ad_group_criterion.age_range.type,
    campaign.id, campaign.name,        -- by_campaign / by_ad_group
    ad_group.id, ad_group.name,        -- by_ad_group only
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM age_range_view
WHERE {filters}
```

---

### `get_gender_performance`
Performance by gender via `gender_view` (single-grain: aggregated to
`(campaign, gender)`).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, campaign/ad-group status filters, date range, `limit`,
`order_by`, `sort_order`.

```sql
SELECT
    ad_group_criterion.gender.type,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM gender_view
WHERE {filters}
```

---

### `get_audience_performance`
Audience targets (in-market, custom, affinity, remarketing).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    ad_group_criterion.user_list.user_list,
    ad_group_criterion.user_interest.user_interest_category,
    ad_group_criterion.custom_audience.custom_audience,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM ad_group_audience_view
WHERE {filters}
```

---

## Performance Max – Asset Group Assets

These three tools cover creative asset auditing for Performance Max campaigns
by querying `asset_group_asset`, which surfaces Google's per-asset
`performance_label` (`PENDING` / `LEARNING` / `LOW` / `GOOD` / `BEST`). They
split by creative medium because the content columns are disjoint per type.

All three share a common parameter set (standard conventions plus
asset-group-specific filters):

- `customer_id`, `campaign_id`, `campaign_name`
- `asset_group_id`, `asset_group_name`
- `campaign_status`, `campaign_primary_status`
- `asset_group_status`, `asset_group_primary_status`
- `performance_label` – `PENDING` / `LEARNING` / `LOW` / `GOOD` / `BEST` / `UNKNOWN`
- `source` – `ADVERTISER` / `AUTOMATICALLY_CREATED`
- `status` – `ENABLED` / `PAUSED` / `REMOVED` (asset-group-asset link status; default excludes `REMOVED`)
- date range, `limit`, `order_by`, `sort_order`

Common row fields: `campaign_id`, `campaign_name`, `campaign_type`,
`asset_group_id`, `asset_group_name`, `asset_id`, `field_type`, `status`,
`performance_label`, `source`, `primary_status`, `primary_status_reasons`,
`approval_status`, `impressions`, `clicks`, `cost`, `conversions`,
`conversion_value`, `ctr`, `cpa`, `roas`.

---

### `get_asset_group_text_assets`
Headlines, long headlines, descriptions.

**Extra parameter:** `field_type` – narrow to a subset of
`{HEADLINE, LONG_HEADLINE, DESCRIPTION}`.
**Extra columns:** `text`.

```sql
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
    asset.text_asset.text,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM asset_group_asset
WHERE asset_group_asset.field_type IN ('HEADLINE', 'LONG_HEADLINE', 'DESCRIPTION')
  AND {filters}
```

---

### `get_asset_group_video_assets`
YouTube video creatives.

**Extra columns:** `youtube_video_id`, `youtube_video_title`, `youtube_url`
(derived: `https://www.youtube.com/watch?v={id}`).

```sql
SELECT
    ...common fields...,
    asset.youtube_video_asset.youtube_video_id,
    asset.youtube_video_asset.youtube_video_title,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM asset_group_asset
WHERE asset_group_asset.field_type = 'YOUTUBE_VIDEO'
  AND {filters}
```

---

### `get_asset_group_image_assets`
Marketing images + logos, labelled by orientation.

**Extra parameter:** `field_type` – narrow to a subset of
`{MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, LOGO, LANDSCAPE_LOGO}`.
**Extra columns:** `orientation` (derived: `Horizontal` / `Square` / `Vertical`
/ `Logo` / `Landscape Logo`), `image_url`, `width`, `height`, `file_size`,
`mime_type`.

```sql
SELECT
    ...common fields...,
    asset.image_asset.full_size.url,
    asset.image_asset.full_size.width_pixels,
    asset.image_asset.full_size.height_pixels,
    asset.image_asset.file_size,
    asset.image_asset.mime_type,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value
FROM asset_group_asset
WHERE asset_group_asset.field_type IN (
    'MARKETING_IMAGE', 'SQUARE_MARKETING_IMAGE', 'PORTRAIT_MARKETING_IMAGE',
    'LOGO', 'LANDSCAPE_LOGO'
  )
  AND {filters}
```

---

## Diagnostics

### `get_keyword_quality_details`
Keywords with Quality Score component breakdown.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, campaign/ad-group status filters, `min_impressions` (default
0), date range, `limit`, `order_by`, `sort_order`.

```sql
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
WHERE {filters}
  AND metrics.impressions >= {min_impressions}
```

---

### `get_ad_extensions`
Assets/extensions attached at campaign and account level (sitelinks, callouts,
structured snippets, call, image, price).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`. (No
`order_by`/`sort_order`.)

```sql
-- campaign assets
SELECT
    asset.id, asset.name, asset.type,
    asset.sitelink_asset.description1,
    asset.sitelink_asset.description2,
    asset.sitelink_asset.link_text,
    asset.callout_asset.callout_text,
    asset.structured_snippet_asset.header,
    asset.structured_snippet_asset.values,
    campaign_asset.campaign,
    campaign_asset.field_type,
    campaign_asset.status,
    metrics.impressions, metrics.clicks, metrics.cost_micros
FROM campaign_asset
WHERE {filters}

-- account-level assets
SELECT
    asset.id, asset.name, asset.type,
    customer_asset.field_type, customer_asset.status,
    metrics.impressions, metrics.clicks
FROM customer_asset
WHERE {filters}
```

---

### `get_bid_strategies`
Campaign-level bidding configuration plus impression-share context.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
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
WHERE {filters}
```

---

### `get_budget_pacing`
Month-to-date spend vs daily budget with EOM projection. Date range is
auto-calculated (month-start → yesterday); no date parameters.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`.

```sql
SELECT
    campaign.id, campaign.name, campaign.status,
    campaign_budget.amount_micros,
    metrics.cost_micros, metrics.conversions,
    metrics.impressions, metrics.clicks
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND segments.date BETWEEN '{month_start}' AND '{yesterday}'
  {campaign_filter}
ORDER BY metrics.cost_micros DESC
```

Computed fields: `mtd_spend`, `daily_budget`, `days_elapsed`, `days_remaining`,
`projected_eom_spend`, `needed_daily_spend_to_hit_target`, `pacing_status`.

---

### `get_landing_page_performance`
Final-URL performance via `landing_page_view`.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
SELECT
    landing_page_view.unexpanded_final_url,
    campaign.id, campaign.name,
    metrics.impressions, metrics.clicks, metrics.cost_micros,
    metrics.conversions, metrics.conversions_value,
    metrics.speed_score,
    metrics.mobile_friendly_clicks_percentage
FROM landing_page_view
WHERE {filters}
```

---

### `get_change_history`
Recent `change_event` rows (who changed what, when). Hard-capped at 200 events.

**Parameters:** `customer_id`, `date_range_days` (default 7).

```sql
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
WHERE change_event.change_date_time >= '{N_days_ago}'
ORDER BY change_event.change_date_time DESC
LIMIT 200
```

---

### `get_campaign_negative_keywords`
Campaign-level negative keywords (exclusions). No metrics, no date range.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`.

```sql
SELECT
    campaign_criterion.keyword.text,
    campaign_criterion.keyword.match_type,
    campaign_criterion.negative,
    campaign.id, campaign.name
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD'
  AND campaign_criterion.negative = TRUE
  {filters}
```

---

### `get_ad_group_negative_keywords`
Ad-group-level negative keywords (exclusions). No metrics, no date range.

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`, `ad_group_id`,
`ad_group_name`, campaign/ad-group status filters.

```sql
SELECT
    ad_group_criterion.keyword.text,
    ad_group_criterion.keyword.match_type,
    ad_group_criterion.negative,
    ad_group.id, ad_group.name,
    campaign.id, campaign.name
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = TRUE
  {filters}
```

---

### `get_impression_share`
Search impression share and lost-IS metrics (budget vs rank).

**Parameters:** `customer_id`, `campaign_id`, `campaign_name`,
`campaign_status`, `campaign_primary_status`, date range, `limit`, `order_by`,
`sort_order`.

```sql
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
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND {filters}
```

---

## Ad-hoc GAQL

### `get_resource_metadata`
List the fields available on a Google Ads resource, for building ad-hoc GAQL.

**Parameters:** `resource` (e.g. `"campaign"`, `"ad_group"`, `"keyword_view"`).

Metric/segment compatibility lives in the MCP resources
`resource://metrics` and `resource://segments`; discovery starts at
`resource://discovery`.

---

### `gaql_search`
Structured GAQL builder – server assembles the query from parts.

**Parameters:**
- `customer_id`
- `resource`: FROM resource name
- `fields`: list of fields to SELECT
- `conditions`: optional list of WHERE predicates (joined with AND)
- `orderings`: optional list of ORDER BY expressions
- `limit`: optional row cap

Only SELECT is issued. The server validates the resource against a known list.

---

### `run_gaql_query`
Raw GAQL for callers that already have a full query.

**Parameters:** `customer_id`, `query` (GAQL SELECT), `max_rows` (default 1000).

Only SELECT is allowed; other statements are rejected.

---

## Tool Surface Summary

| # | Tool | Date Range | Category |
|---|------|------------|----------|
| 1 | `get_accessible_accounts` | – | Account |
| 2 | `get_account_info` | – | Account |
| 3 | `get_conversion_actions` | – | Account |
| 4 | `get_campaign_labels` | – | Account |
| 5 | `get_ad_group_labels` | – | Account |
| 6 | `get_resource_metadata` | – | Query |
| 7 | `get_campaigns_report` | Yes | Reporting |
| 8 | `get_ad_groups_report` | Yes | Reporting |
| 9 | `get_keywords_overall` | Yes | Reporting |
| 10 | `get_keywords_by_campaign` | Yes | Reporting |
| 11 | `get_keywords_by_ad_group` | Yes | Reporting |
| 12 | `get_daily_performance` | Yes | Reporting |
| 12a | `get_daily_performance_by_campaign` | Yes | Reporting |
| 12b | `get_conversion_breakdown_overall` | Yes | Reporting |
| 12c | `get_conversion_breakdown_by_campaign` | Yes | Reporting |
| 12d | `get_daily_conversion_breakdown` | Yes | Reporting |
| 13 | `get_search_terms` | Yes | Reporting |
| 14 | `get_geo_performance` | Yes | Reporting |
| 15 | `get_device_performance` | Yes | Reporting |
| 16 | `get_ad_performance` | Yes | Reporting |
| 17 | `get_age_overall` | Yes | Reporting |
| 18 | `get_age_by_campaign` | Yes | Reporting |
| 19 | `get_age_by_ad_group` | Yes | Reporting |
| 20 | `get_gender_performance` | Yes | Reporting |
| 21 | `get_audience_performance` | Yes | Reporting |
| 22 | `get_hourly_performance` | Yes | Reporting |
| 23 | `get_search_term_keyword_mapping` | Yes | Reporting |
| 24 | `get_asset_group_text_assets` | Yes | Reporting (PMax) |
| 25 | `get_asset_group_video_assets` | Yes | Reporting (PMax) |
| 26 | `get_asset_group_image_assets` | Yes | Reporting (PMax) |
| 27 | `get_keyword_quality_details` | Yes | Diagnostics |
| 28 | `get_ad_extensions` | Yes | Diagnostics |
| 29 | `get_bid_strategies` | Yes | Diagnostics |
| 30 | `get_budget_pacing` | Auto (MTD) | Diagnostics |
| 31 | `get_landing_page_performance` | Yes | Diagnostics |
| 32 | `get_change_history` | `date_range_days` only | Diagnostics |
| 33 | `get_campaign_negative_keywords` | – | Diagnostics |
| 34 | `get_ad_group_negative_keywords` | – | Diagnostics |
| 35 | `get_impression_share` | Yes | Diagnostics |
| 36 | `gaql_search` | Optional | Query |
| 37 | `run_gaql_query` | Optional | Query |

---

## Helper: `build_date_clause`

Defined in `src/google_ads_mcp/google_ads/utils.py`. Returns a
`ResolvedDateRange` with a GAQL `clause` plus a response-friendly dict
(`{date_from, date_to}` or `{preset}`) surfaced in every tool's metadata line.

```python
from datetime import date, timedelta

def build_date_clause(
    date_range_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ResolvedDateRange:
    """Build a GAQL date filter clause from explicit or relative inputs.

    - date_from + date_to (both required together) → explicit BETWEEN
    - date_range_days=N             → last N days ending yesterday
    - neither                       → DURING LAST_30_DAYS
    """
    if (date_from and not date_to) or (date_to and not date_from):
        raise ValueError("date_from and date_to must be provided together.")
    if date_from and date_to:
        # ISO-parse, validate start ≤ end, return BETWEEN clause
        ...
    if date_range_days:
        yesterday = date.today() - timedelta(days=1)
        start = yesterday - timedelta(days=date_range_days - 1)
        return ResolvedDateRange(
            clause=f"segments.date BETWEEN '{start}' AND '{yesterday}'",
            date_from=str(start), date_to=str(yesterday),
        )
    return ResolvedDateRange(
        clause="segments.date DURING LAST_30_DAYS", preset="LAST_30_DAYS"
    )
```

---

## Skills → Tools Coverage Matrix

| Skill | Tools Used |
|-------|------------|
| #1 CPA Diagnostics | `get_campaigns_report`, `get_daily_performance_by_campaign`, `get_device_performance`, `get_hourly_performance` |
| #2 Wasted Spend | `get_search_terms`, `get_campaign_negative_keywords`, `get_ad_group_negative_keywords`, `get_keywords_overall` |
| #3 Budget Planner | `get_campaigns_report`, `get_budget_pacing`, `get_daily_performance` |
| #6 Anomaly Detection | `get_daily_performance`, `get_daily_performance_by_campaign`, `get_hourly_performance`, `get_change_history`, `get_impression_share` |
| #7 Search Term Mining | `get_search_terms`, `get_search_term_keyword_mapping`, `get_keywords_by_ad_group` |
| #11 Bid Strategy | `get_bid_strategies`, `get_campaigns_report`, `get_impression_share` |
| #12 Day/Hour Breakdown | `get_hourly_performance` |
| #14 Quality Score | `get_keyword_quality_details`, `get_ad_performance`, `get_landing_page_performance` |
| #17 Account Structure | `get_campaigns_report`, `get_ad_groups_report`, `get_keywords_by_ad_group`, `get_campaign_labels`, `get_ad_group_labels` |
| #19 ROAS Forecasting | `get_daily_performance`, `get_campaigns_report`, `get_conversion_actions` |
| #20 Keyword Cannibalization | `get_search_term_keyword_mapping`, `get_keywords_by_campaign`, `get_campaign_negative_keywords`, `get_ad_group_negative_keywords` |
| #21 Extension Audit | `get_ad_extensions`, `get_campaigns_report` |
| #24 Geo Analysis | `get_geo_performance` |
| #25 Device Split | `get_device_performance` |
| #26 Attribution | `get_conversion_actions`, `get_conversion_breakdown_overall`, `get_conversion_breakdown_by_campaign`, `get_daily_conversion_breakdown`, `get_campaigns_report` |
| #27 Pacing | `get_budget_pacing`, `get_campaigns_report`, `get_account_info` |
| #30 Weekly Summary | `get_account_info`, `get_campaigns_report`, `get_daily_performance`, `get_hourly_performance` |
| #37 Google Ads Audit | All tools (comprehensive audit) |
