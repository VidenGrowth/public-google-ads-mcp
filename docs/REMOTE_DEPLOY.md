# Remote deploy – HTTP + per-user Google OAuth

Host one shared instance of the Google Ads MCP server.

This guide uses **Google Cloud Run**, but **any container host works**.

## How it works

The server is a pure OAuth 2.0 **Resource Server** (RFC 9728). It does not run
an OAuth flow – the MCP client obtains a Google token directly from Google, and
the server only verifies that token and forwards it to the Google Ads API.

```
MCP client ──(1) discover───►  /.well-known/oauth-protected-resource
                                  (server points at https://accounts.google.com)
           ──(2) authorize──►  Google consent (openid, email, adwords)
                                  using the OAuth client id+secret from the connector
           ◄─(3) redirect────  client's own callback (e.g. claude.ai/api/mcp/auth_callback)
           ──(4) tool calls──►  /  with the Google token as a Bearer header
                                   │
                                   ▼
                 server verifies the token (aud + adwords scope) and
                 forwards it as-is to the Google Ads API
```

Because Google does **not** support Dynamic Client Registration, the client uses
a pre-created OAuth client whose id+secret are configured in the connector (see
[Connect a client](#connect-a-client)). Each user's Google token (carrying the
`adwords` scope) is forwarded per request, so **authorization is exactly what
their Google account can do**. The server stores only the operator's developer
token – **no OAuth client secret, no user credentials, no email allowlist**.

This also means the server is **stateless**: nothing to persist between
requests, so Cloud Run `--min=0` (scale to zero) is safe – there is no OAuth
session or client-registration state to lose on cold start or across instances.

## Prerequisites

1. A Google Cloud project with **Cloud Run**, **Secret Manager**, and the
   **Google Ads API** enabled.
2. A **Google Ads developer token**.
3. An **OAuth 2.0 Web client** in that project (APIs & Services → Credentials).
4. A runtime **service account** with `roles/secretmanager.secretAccessor` on the
   developer-token secret you create below.

### OAuth client + consent screen

- **Redirect URIs** are the **MCP clients' callbacks** – not a URL on this
  server (the server never receives the OAuth redirect). Register the ones for
  the clients you support:

  | Redirect URI | Client |
  |---|---|
  | `https://claude.ai/api/mcp/auth_callback` | Claude.ai web |
  | `https://claude.com/api/mcp/auth_callback` | Claude.ai web (alt domain) |
  | `http://localhost:3334/oauth/callback` | Claude Desktop via `mcp-remote` |
  | `http://127.0.0.1:3334/oauth/callback` | `mcp-remote` loopback alt |
  | `http://localhost:3118/callback` | Claude Code CLI (`--callback-port 3118`) |
  | `http://127.0.0.1:3118/callback` | Claude Code CLI loopback alt |

- **Scopes** on the consent screen: `openid`, `.../auth/userinfo.email`, and
  `.../auth/adwords`. `adwords` is a sensitive scope: in Testing mode it works
  for up to 100 listed test users without verification; publishing requires
  Google review.

## Environment variables

| Var | Value | Notes |
|---|---|---|
| `MCP_TRANSPORT` | `http` | set in the Dockerfile by default; the HTTP endpoint is always OAuth-authenticated |
| `MCP_HTTP_PATH` | `/` | mounts MCP at the root path (friendliest for hosted chat clients) |
| `GOOGLE_OAUTH_CLIENT_ID` | your Web client ID | not secret; used only to check each token's `aud` claim |
| `RESOURCE_SERVER_URL` | public service URL | advertised in `/.well-known/oauth-protected-resource`; must match what clients connect to |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | your developer token | **Secret** |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | *(optional)* MCC id | only if all users operate through one manager account |
| `LOG_LEVEL` | `INFO` *(default)* | observability logger |

Note: there is **no** `GOOGLE_OAUTH_CLIENT_SECRET` on the server – the client
holds it. And no server-side `GOOGLE_ADS_REFRESH_TOKEN` / `CLIENT_ID` /
`CLIENT_SECRET` either; those are the *local* stdio path only.

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

# OAuth metadata is advertised, pointing at Google as the authorization server:
curl -s "$URL/.well-known/oauth-protected-resource" | jq
# -> authorization_servers: ["https://accounts.google.com/"]
# -> scopes_supported includes .../auth/adwords

# there is NO authorization-server / DCR endpoint (this is a resource server):
curl -s -o /dev/null -w '%{http_code}\n' "$URL/.well-known/oauth-authorization-server"
# -> 404

# unauthenticated tool calls are rejected:
curl -si -X POST "$URL/" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# -> 401 with a WWW-Authenticate: Bearer header
```

## Connect a client

Because the server points clients at Google (which has no Dynamic Client
Registration), each client must be given the **OAuth client id + secret** of the
Web client you created. For an enterprise rollout this is configured once in the
admin panel and pushed to users – they never paste anything.

**Hosted chat clients (Claude.ai, ChatGPT, …):** add a custom MCP connector in
the app's settings, paste the service URL, and under **Advanced** provide the
OAuth client id + secret. On Claude.ai: Settings → Connectors → *Add custom
connector*. On first connect you're sent through Google's consent screen
(including Google Ads access); after consent the tools appear.

**Desktop / CLI clients (Claude Desktop, Claude Code, …):** bridge stdio to the
remote server with `mcp-remote`, passing the client credentials:

```json
{
  "mcpServers": {
    "google-ads-remote": {
      "command": "npx",
      "args": [
        "mcp-remote", "https://<service-url>/",
        "--static-oauth-client-info",
        "{\"client_id\":\"<CLIENT_ID>\",\"client_secret\":\"<CLIENT_SECRET>\"}"
      ]
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
