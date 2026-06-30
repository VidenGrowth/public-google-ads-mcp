# Google Ads MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives an
LLM (Claude, Copilot, …) **read-only** access to Google Ads account data –
campaigns, ad groups, keywords, search terms, segmented performance reports,
bidding, budgets, conversions, Performance Max assets, labels, change history,
impression share, plus an ad-hoc GAQL escape hatch.

It is a thin wrapper over Google Ads' GAQL `search_stream` API. Every tool takes
a `customer_id` per request, so one running server can query any account the
authenticated credentials can reach.

## Two ways to run

| | Local (stdio) | Remote (HTTP + OAuth) |
|---|---|---|
| **Who it's for** | An individual on their own machine | A team sharing one hosted instance |
| **Auth to Google Ads** | Your own refresh-token credentials | Each user signs in with **their own** Google account; their token is forwarded to the Ads API, so they only see accounts they personally can access |
| **The server holds** | Your full credentials | Only the developer token (no OAuth secret) |
| **Clients** | Claude Desktop, VS Code/Copilot, any stdio MCP client | Claude.ai web connector, Claude Desktop/Code |
| **Setup** | This README, below | [docs/REMOTE_DEPLOY.md](docs/REMOTE_DEPLOY.md) |

Most people want **Local**. Start there.

## What it does

**Read-only tools**, grouped:

- **Accounts** – account discovery, metadata, conversion actions, labels
- **Reporting** – campaigns, ad groups, keywords, search terms, geo / device / demographic segments, Performance Max assets
- **Diagnostics** – Quality Score, ad extensions, bid strategies, budget pacing, change history, negative keywords, impression share
- **Query** – raw GAQL `SELECT` + a structured GAQL builder
- **Metadata** – selectable / filterable / sortable fields per GAQL resource

Full catalog with per-tool descriptions: **[docs/TOOLS.md](docs/TOOLS.md)**.

---

## Prerequisites

- [**uv**](https://docs.astral.sh/uv/getting-started/installation/) – Python package/runtime manager.
- A **Google Cloud project** with the [Google Ads API enabled](https://console.cloud.google.com/apis/library/googleads.googleapis.com).
- A **Google Ads developer token** ([how to get one](https://developers.google.com/google-ads/api/docs/get-started/dev-token)).
- An **OAuth 2.0 client** in that project (Desktop or Web type) – used to generate your refresh token.

---

## Local setup (stdio)

### 1. Clone and install

```bash
git clone https://github.com/VidenGrowth/public-google-ads-mcp google-ads-mcp
cd google-ads-mcp
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
# edit .env (e.g. `nano .env`) and fill in your credentials
```

Fill in (see [.env.example](.env.example) for the full list):

- `GOOGLE_ADS_DEVELOPER_TOKEN`
- `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`
- `GOOGLE_ADS_REFRESH_TOKEN` *(generate it in the next step)*
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` *(optional – only when operating through a manager/MCC account; digits, no dashes)*

The target `customer_id` is **not** in `.env`; the agent passes it per request.

### 3. Generate a refresh token

```bash
uv run auth/generate_refresh_token.py -c client_secret.json
```

Sign in with a Google account that can access the Ads accounts you want, then
paste the printed token into `.env` as `GOOGLE_ADS_REFRESH_TOKEN`.
Full walkthrough: [auth/README.md](auth/README.md).

### 4. Test locally

```bash
uv run python scripts/smoke_test.py
```

Expected: `✓ server wired up – 41 tools registered`, followed by `get_accessible_accounts`
returning your accounts. If credentials are missing you'll get a clear
`<error>{"error":"Google Ads client not configured. …"}</error>` instead – fix `.env`
and re-run.

Run the test suite anytime with:

```bash
uv run --with pytest pytest tests/ -q
```

### 5. Connect a client

**Claude Desktop** (`claude_desktop_config.json` – macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "google-ads": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/google-ads-mcp", "run", "google-ads-mcp"]
    }
  }
}
```

Restart Claude Desktop fully (quit from the tray/menu, not just close the window).

Then enable `Chat > MCP` in settings, run **`MCP: Start Server`** from the Command

---

## Example prompts

Once connected, try (replace the ID with one of your accounts):

- *"Show me all campaigns for customer 1234567890"*
- *"Find wasted spend in search terms for customer 1234567890"*
- *"Which keywords have quality scores below 5 for customer 1234567890?"*
- *"Compare device and geographic performance for customer 1234567890 over the last 30 days"*
- *"Show the age + gender breakdown for customer 1234567890"*
- *"Is customer 1234567890 on pace to spend its budget this month?"*

Parameter conventions (date ranges, ID/name filters, status filters, sorting) are
documented in [docs/TOOLS_DESIGN.md](docs/TOOLS_DESIGN.md).

---

## Remote deploy

To host shared instance where each teammate signs in with their own Google account – no per-user install, and everyone only sees the Ads accounts they can access – deploy the HTTP transport with Google OAuth.
The server is a pure OAuth Resource Server: the MCP client signs the user in with Google, and the server verifies each request's token and forwards it to the Ads API. It holds only the developer token – no OAuth client secret.

Full guide: **[docs/REMOTE_DEPLOY.md](docs/REMOTE_DEPLOY.md)**.

---

## How authentication works

- **Local (stdio):** the server uses *your* refresh-token credentials. There is
  no MCP-layer auth – the server runs on your machine under your control.
- **Remote (HTTP):** the server is an OAuth 2.0 Resource Server (RFC 9728). The
  MCP client obtains a Google token directly (Google's own OAuth flow), and the
  server verifies each request's token – checking the `aud` claim and the
  `adwords` scope – then forwards it to the Google Ads API. Authorization is
  whatever that user's Google account can do. The server runs no OAuth flow and
  stores **no** secret beyond the operator's developer token; the OAuth client
  secret lives in the connector config, not on the server.

---

## Architecture

See [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) for a directory tour and request
flow, and [docs/TOOLS_DESIGN.md](docs/TOOLS_DESIGN.md) for the design conventions
every tool follows.

## License

[MIT](LICENSE).
