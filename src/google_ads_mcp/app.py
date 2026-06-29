"""MCP application factory for the Google Ads server."""

from dotenv import load_dotenv
from fastmcp import FastMCP

from google_ads_mcp.resources import register_resources
from google_ads_mcp.tools import register_tools

load_dotenv()

INSTRUCTIONS = """Google Ads MCP server. Read-only access to Google Ads account data: \
accounts, campaigns, ad groups, keywords, search terms, segmented performance reports, \
bids, budgets, conversions, assets, labels, change history, impression share, plus \
ad-hoc GAQL queries.

## Common parameter conventions

All reporting/diagnostic tools share the same conventions. Each tool's docstring \
describes only what is unique to it; general rules below apply everywhere.

- **customer_id** (required): Google Ads customer ID, with or without dashes \
  (e.g. "123-456-7890" or "1234567890").
- **login_customer_id** (optional): manager (MCC) customer ID, with or without \
  dashes. Set it ONLY when `customer_id` is a client account reached *through* a \
  manager (the API requires the manager in the `login-customer-id` header for \
  client accounts). Omit it for accounts that are directly accessible to the \
  signed-in user.
- **campaign_id / ad_group_id**: Single numeric string or list of strings. List \
  produces an `IN (...)` filter. Digits only.
- **campaign_name / ad_group_name**: Case-insensitive substring match. Single \
  string → matches names containing it. List → matches names containing ANY value. \
  Exact names are not required.
- **Date range** (mutually exclusive; omit both → defaults to `LAST_30_DAYS`):
    - `date_range_days`: int, last N days ending yesterday (inclusive).
    - `date_from` + `date_to`: ISO 'YYYY-MM-DD' (both required together, inclusive).
- **limit**: int, max rows. Omit for tool-specific default (usually unlimited).
- **order_by**: One of `cost`, `impressions`, `clicks`, `conversions`, \
  `conversion_value`, `conversions_by_conversion_date`, \
  `conversion_value_by_conversion_date`, `all_conversions`, \
  `all_conversions_value`. Omit for the tool's default ordering. \
  The `*_by_conversion_date` and `all_conversions*` aliases are only useful \
  with the conversion-breakdown tools.
- **sort_order**: `ASC` or `DESC` (default `DESC`).

## Output format

Tools return XML-tagged blocks. A successful response is:

```
<meta>{"applied":{"date_range":{...},"filters":{...},"row_count":N}, ...}</meta>
<data>
col_a\tcol_b\tcol_c
v1\tv2\tv3
...
</data>
```

- `<meta>` always carries an `applied` object with the resolved `date_range`, \
  active `filters`, and `row_count`. Tool-specific fields (e.g. `summary`, \
  `query`, `truncated`, `month_start`) sit at the top level next to `applied`.
- `<data>` wraps a TSV grid. The first line inside `<data>` is the column \
  header; subsequent lines are rows. Empty result sets omit the `<data>` block.
- Multi-table tools (e.g. `get_ad_extensions`) emit one `<table name="...">` \
  block per section instead of `<data>`. Same internal TSV shape.
- Numeric cost values are already in account currency (micros converted \
  automatically).
- Errors come back as `<error>{"error":"..."}</error>` – no `<meta>` or \
  `<data>` block. Dispatch on the opening tag.

## Ad-hoc GAQL workflow

1. List available fields with `get_resource_metadata(resource)`.
2. Consult `resource://metrics` and `resource://segments` for metric/segment \
   compatibility with the chosen resource.
3. Build a query via `gaql_search` (structured: resource + fields + conditions) or \
   `run_gaql_query` (raw GAQL). Only SELECT is allowed.

Reference resources: `resource://discovery`, `resource://metrics`, \
`resource://segments`, `resource://release-notes`."""


def create_mcp(auth=None) -> FastMCP:
    """Create and configure the Google Ads FastMCP app.

    ``auth`` is an optional FastMCP auth provider used by the remote HTTP
    transport (see ``server.py``). The local stdio transport runs with no auth.
    Host/port/path are passed to ``mcp.run()`` by the caller, not here.
    """
    mcp = FastMCP("google-ads", instructions=INSTRUCTIONS, auth=auth)
    register_tools(mcp)
    register_resources(mcp)
    return mcp
