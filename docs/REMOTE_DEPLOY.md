# Remote deploy – HTTP + per-user Google OAuth

Host one shared instance of the Google Ads MCP server.

This guide uses **Google Cloud Run**, but **any container host works**.

## How it works

```
MCP client ──(1) discover───►  /.well-known/oauth-protected-resource
           ──(2) DCR─────────►  /register        (server registers the client dynamically)
           ──(3) authorize───►  /authorize  ──►  Google consent (openid, email, adwords)
           ◄─(4) redirect─────  /auth/callback   (Google → server → client)
           ──(5) tool calls──►  /mcp  with a FastMCP token
                                   │
                                   ▼
                 server swaps the FastMCP token for the upstream
                 Google token and forwards it to the Google Ads API
```

The server (`fastmcp`'s `GoogleProvider`) is an OAuth proxy with Dynamic Client
Registration, so clients connect in one click – no pasted client ID or secret.
Each user's Google token (carrying the `adwords` scope) is forwarded per request,
so **authorization is exactly what their Google account can do**. The server stores
only the operator's developer token and OAuth client_id/secret.

## Prerequisites

1. A Google Cloud project with **Cloud Run**, **Secret Manager**, and the
   **Google Ads API** enabled.
2. A **Google Ads developer token**.
3. An **OAuth 2.0 Web client** in that project (APIs & Services → Credentials).
4. A runtime **service account** with `roles/secretmanager.secretAccessor` on the
   two secrets you create below.

### OAuth client + consent screen

- **Redirect URI** (exactly one): `<RESOURCE_SERVER_URL>/auth/callback`
  where `RESOURCE_SERVER_URL` is the public URL of your service. On Cloud Run the
  URL is deterministic – `https://<service>-<project_number>.<region>.run.app` –
  so you can set it before the first deploy.
- **Scopes** on the consent screen: `openid`, `.../auth/userinfo.email`, and
  `.../auth/adwords`.

## Environment variables

| Var | Value | Notes |
|---|---|---|
| `MCP_TRANSPORT` | `http` | set in the Dockerfile by default; the HTTP endpoint is always OAuth-authenticated |
| `MCP_HTTP_PATH` | `/` | mounts MCP at the root path (friendliest for hosted chat clients) |
| `GOOGLE_OAUTH_CLIENT_ID` | your Web client ID | not secret |
| `GOOGLE_OAUTH_CLIENT_SECRET` | your Web client secret | **Secret** |
| `RESOURCE_SERVER_URL` | public service URL | must match what clients connect to |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | your developer token | **Secret** |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | *(optional)* MCC id | only if all users operate through one manager account |
| `LOG_LEVEL` | `INFO` *(default)* | observability logger |

Note: no server-side `GOOGLE_ADS_REFRESH_TOKEN` /
`CLIENT_ID` / `CLIENT_SECRET` – those are the *local* stdio path only.

## Deploy

```bash
cp deploy/deploy.sh.example deploy/deploy.sh   # gitignored
# edit deploy/deploy.sh: project id/number, service account, OAuth client id
./deploy/deploy.sh
```

The script creates the env/secret wiring and prints post-deploy checks. See
[deploy/deploy.sh.example](../deploy/deploy.sh.example) for the secret-creation
commands.

## Verify

```bash
URL=https://<service>-<project_number>.<region>.run.app

# OAuth metadata is advertised:
curl -s "$URL/.well-known/oauth-protected-resource" | jq
# -> scopes_supported includes .../auth/adwords

# the authorization server (proxy) exposes DCR:
curl -s "$URL/.well-known/oauth-authorization-server" | jq '.registration_endpoint'

# unauthenticated tool calls are rejected:
curl -si -X POST "$URL/" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# -> 401 with a WWW-Authenticate: Bearer header
```

## Connect a client

Any MCP client supporting remote HTTP + OAuth can connect. On first connect you're
sent through Google's consent screen (including Google Ads access); after consent
the tools appear – no client ID or secret to paste.

**Hosted chat clients (Claude.ai, ChatGPT, …):** add a custom MCP connector in the
app's settings and paste the service URL. On Claude.ai: Settings → Connectors →
*Add custom connector*.

**Desktop / CLI clients (Claude Desktop, Claude Code, …):** bridge stdio to the
remote server with `mcp-remote`:

```json
{
  "mcpServers": {
    "google-ads-remote": {
      "command": "npx",
      "args": ["mcp-remote", "https://<service-url>/"]
    }
  }
}
```

## Observability

Each tool call emits one line to Cloud Logging:

```
tool_call tool=get_accessible_accounts user=alice@example.com args=
tool_done tool=get_accessible_accounts user=alice@example.com duration_ms=418
```

`args=` lists argument **names** only – values are never logged. `user` is the
authenticated caller's Google email.

```bash
gcloud run services logs read google-ads-mcp \
  --region=<region> --project=<project-id> --limit=200 | grep tool_
```
