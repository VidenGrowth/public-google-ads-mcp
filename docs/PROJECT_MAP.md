# Project Map – Google Ads MCP Server

## Architecture Overview

```
Client (Claude.ai / Desktop / Copilot / IDE)
       │
       │  stdio (local)    OR    http (remote, Cloud Run)
       ▼                          │ + Bearer token (client obtains it from Google directly)
                                  ▼
                            auth.py (RemoteAuthProvider – OAuth resource server)
                                  │  verifies the user's Google token (aud + adwords scope)
                                  ▼
  server.py ──► app.py ──► register_tools()
                  │
       ┌──────────┼──────────┬──────────────┬───────────┐
       ▼          ▼          ▼              ▼           ▼
   accounts   reporting  diagnostics     query      metadata
   (5 tools) (24 tools)  (9 tools)     (2 tools)   (1 tool)
       │          │          │              │          │
       └── every fn wrapped by observability.log_tool_call ──┘
                       │
              google_ads/client.py   ◄── require_client()
                       │                   remote: per-user OAuth token forwarded to the Ads API
                       │                   local:  GoogleAdsClient from env-var refresh token
              google_ads/utils.py    ◄── GAQL builders, formatting, validation
                       │
              Google Ads API (gRPC)
```

## Directory Structure

```
google-ads-mcp/
├── src/google_ads_mcp/          # Application source
│   ├── server.py                # Entry point – switches stdio/http by MCP_TRANSPORT
│   ├── app.py                   # FastMCP factory – create_mcp(auth=…)
│   ├── auth.py                  # RemoteAuthProvider factory (OAuth resource server, remote HTTP)
│   ├── observability.py         # setup_logging() + log_tool_call decorator
│   ├── google_ads/              # API client layer
│   │   ├── client.py            # require_client(), search_rows(); per-user token or env creds
│   │   └── utils.py             # All helpers: fmt, fmt_table, GAQL builders, validation
│   ├── resources/               # MCP resources (discovery, metrics, segments, release-notes)
│   └── tools/                   # MCP tool definitions
│       ├── __init__.py          # register_tools() – calls all 5 modules
│       ├── accounts.py          # Account discovery & metadata (5 tools)
│       ├── reporting.py         # Performance reports & segmentation (24 tools)
│       ├── diagnostics.py       # Audit, QS, pacing, change history (9 tools)
│       ├── query.py             # Custom GAQL query execution (2 tools)
│       └── metadata.py          # Resource field metadata (1 tool)
│
├── auth/                        # OAuth2 refresh-token generation (for local stdio use)
│   ├── README.md
│   └── generate_refresh_token.py
├── deploy/                      # Cloud Run remote-deploy template
│   ├── deploy.sh.example        # Deploy command template (inline --set-env-vars from shell vars)
│   └── (deploy.sh – gitignored, local only)
├── scripts/                     # Helper scripts
│   ├── smoke_test.py            # Local smoke test (lists tools + calls get_accessible_accounts)
│   ├── update_references.py     # Regenerate resources/gaql_resources.txt from the live API
│   ├── setup-windows-claude-desktop.ps1
│   └── generate-refresh-token-windows.ps1
├── docs/                        # Documentation
│   ├── PROJECT_MAP.md           # This file
│   ├── TOOLS.md                 # Full tool catalog (41 tools, grouped)
│   ├── TOOLS_DESIGN.md          # Tool API specification
│   └── REMOTE_DEPLOY.md         # Remote HTTP + per-user OAuth deploy guide
├── tests/                       # pytest suite
│   ├── test_tool_contracts.py   # Tool behavior + GAQL shape
│   └── test_auth.py             # Auth provider + token-forwarding unit tests
│
├── .env.example                 # Local + remote env var template
├── LICENSE                      # MIT
├── Dockerfile                   # Cloud Run image – sets MCP_TRANSPORT=http
│
├── pyproject.toml               # Dependencies, entry point, metadata
├── .env.example                 # Local stdio credentials template
└── uv.lock                      # Locked dependency versions
```

## Request Flow

1. Client sends tool call via MCP stdio transport
2. `server.py` → `app.py` → FastMCP routes to registered tool function
3. Tool function in `tools/*.py` builds GAQL query using helpers from `utils.py`
4. `client.py:search_rows()` executes query via `GoogleAdsService.search_stream()`
5. Tool formats rows → `fmt_table()` returns an XML envelope: `<meta>` JSON + `<data>`/`<table>` TSV
6. Response goes back to client through MCP

## Source Modules

### server.py – Entry Point
- Creates MCP app via `create_mcp()`
- Runs on stdio transport (used by Claude Desktop, Copilot, VS Code)
- Entry point in pyproject.toml: `google_ads_mcp.server:main`

### app.py – App Factory
- Loads `.env`, creates `FastMCP("google-ads")` with instructions string
- Calls `register_tools(mcp)` to wire up all tool handlers

### google_ads/client.py – API Client
- **`require_client()`** – returns the client for the current request: a per-user
  client built from the forwarded OAuth token (remote HTTP), else the
  env-credential singleton (local stdio); raises `ClientError` if neither is set
- **`get_google_ads_client()`** – builds/caches the local singleton from env vars
- **`search_rows(customer_id, query)`** – executes GAQL via `search_stream()`, returns flat list of rows
- **`manager_customer_id()`** – returns the configured MCC/login customer ID (local MCC mode)

### google_ads/utils.py – Helpers

**Output formatting:**
| Function | Purpose |
|----------|---------|
| `fmt(data)` | Compact JSON (for errors, single objects) |
| `fmt_table(meta, rows)` | `<meta>` JSON + `<data>`/`<table>` TSV envelope (saves ~3-4x tokens) |
| `error_response(exc)` | `<error>{"error":"message"}</error>` |

**GAQL query builders:**
| Function | Purpose |
|----------|---------|
| `build_date_clause(days, from, to)` | → `ResolvedDateRange` with WHERE clause |
| `build_where(*clauses)` | Join non-empty clauses with AND |
| `build_order_by(field, direction, default)` | ORDER BY from friendly name (cost, clicks...) |
| `build_limit(limit)` | LIMIT clause or empty string |
| `id_filter(field, name, value)` | `= X` or `IN (X, Y)` for single/list IDs |
| `name_filter(field, value)` | `LIKE '%X%'` or `REGEXP_MATCH` for single/list names |

**Validation:**
| Function | Purpose |
|----------|---------|
| `normalize_customer_id(id)` | Strip dashes, validate digits |
| `normalize_numeric_id(name, value)` | Validate numeric filter ID |
| `normalize_positive_int(name, value)` | Validate > 0 |
| `parse_iso_date(value, name)` | Parse YYYY-MM-DD |

**Metric helpers:**
| Function | Purpose |
|----------|---------|
| `cost_from_micros(micros)` | ÷ 1,000,000 → currency |
| `safe_divide(num, denom)` | Division with zero-check |
| `safe_percentage(num, denom)` | Percentage with zero-check |
| `enum_name(value)` | Proto enum → string name |

## Tools

The server registers **41 tools** across the five `tools/*.py` modules shown in
the directory tree above (accounts 5, reporting 24, diagnostics 9, query 2,
metadata 1). Rather than duplicate the list here, see:

- **[TOOLS.md](TOOLS.md)** – the catalog: every tool with a one-line description.
- **[TOOLS_DESIGN.md](TOOLS_DESIGN.md)** – per-tool parameters and the exact GAQL
  each tool issues (the `FROM` resource, filters, and segmentation).

## Filter Parameter Types

All filter params (`campaign_id`, `campaign_name`, `ad_group_id`, `ad_group_name`) accept:
- **Single value**: `"12345"` → `= 12345` / `LIKE '%name%'`
- **List**: `["123", "456"]` → `IN (123, 456)` / `REGEXP_MATCH '(?i).*(a|b).*'`
- **None**: filter not applied

## Output Format

Tools return an XML-tagged envelope: a `<meta>` JSON block followed by a
`<data>` (or `<table name="...">`) block wrapping a TSV grid.

```
<meta>{"applied":{"date_range":{"preset":"LAST_30_DAYS"},"row_count":3}}</meta>
<data>
campaign_id	campaign_name	clicks	cost	ctr
123	Brand	500	12.50	3.2
456	Search	300	8.20	2.1
789	Display	150	5.00	0.8
</data>
```

- `<meta>`: compact JSON. An `applied` object carries the resolved `date_range`,
  active `filters`, and `row_count`; tool-specific fields (`summary`, `query`,
  `truncated`, ...) sit at the top level next to `applied`.
- `<data>`: TSV grid – first line is the header, then one tab-joined row per line.
  Empty result sets omit the block.
- Multi-table tools emit one `<table name="...">` block per section (e.g.
  `<table name="age">`, `<table name="gender">`) instead of a single `<data>`.
- Cells with tabs/newlines are sanitized to spaces; lists are joined with `|`.
- Errors come back as `<error>{"error":"..."}</error>` – no `<meta>`/`<data>`.

## Configuration

### Environment Variables

Two credential paths, selected by transport (`google_ads/client.py`):

**Local (stdio)** – `get_google_ads_client()` builds one client from env vars:
1. `GOOGLE_ADS_CONFIGURATION_FILE_PATH` (google-ads.yaml) – if set
2. else `GOOGLE_ADS_REFRESH_TOKEN` + `GOOGLE_ADS_DEVELOPER_TOKEN` + `GOOGLE_ADS_CLIENT_ID`/`CLIENT_SECRET`

**Remote (HTTP)** – `require_client()` forwards the signed-in user's Google OAuth
token (with the `adwords` scope) to the Ads API per request; the server supplies
only `GOOGLE_ADS_DEVELOPER_TOKEN`. No refresh token is stored server-side.

#### Local / stdio
| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Yes | API developer token |
| `GOOGLE_ADS_CLIENT_ID` | Yes | OAuth2 client ID for the refresh-token flow |
| `GOOGLE_ADS_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `GOOGLE_ADS_REFRESH_TOKEN` | Yes | OAuth2 refresh token (generate via `auth/`) |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | No | MCC id (digits only); only when operating through a manager account |
| `GOOGLE_ADS_CONFIGURATION_FILE_PATH` | No | Alternative: path to a google-ads.yaml |

#### Remote transport & auth (Cloud Run)
The `http` transport is a pure OAuth resource server: it verifies each request's
Google token and forwards it to the Ads API. It holds no OAuth client secret.

| Variable | Description |
|----------|-------------|
| `MCP_TRANSPORT` | `stdio` (default) \| `http` |
| `HOST`, `PORT` | Listen interface/port for HTTP transport |
| `MCP_HTTP_PATH` | MCP mount path (default `/mcp/`; `/` is friendliest for Claude.ai) |
| `GOOGLE_OAUTH_CLIENT_ID` | Google Web OAuth client ID; checked against each token's `aud` claim |
| `RESOURCE_SERVER_URL` | Public service URL (advertised in protected-resource metadata) |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | API developer token (from Secret Manager) |
| `LOG_LEVEL` | `INFO` (default) – controls the observability logger |