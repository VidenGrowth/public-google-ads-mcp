"""Remote (HTTP) authentication for the Google Ads MCP server.

When the server runs behind an HTTP transport it authenticates each user with
their own Google account via FastMCP's ``GoogleProvider`` (an OAuth proxy). The
remote endpoint is always authenticated – there is no unauthenticated HTTP mode.
Two things fall out of that single sign-in:

* **Access control** – only users who can complete Google's OAuth consent for
  this app's OAuth client reach the tools. There is no email allowlist; access
  is scoped naturally by what each user's Google account can do.
* **Per-user Ads API access** – the Google access token obtained during sign-in
  carries the ``adwords`` scope and is forwarded to the Google Ads API (see
  ``google_ads/client.py``), so every user only sees the accounts they
  personally have access to. The server holds just the developer token.

The proxy lets MCP clients (e.g. Claude.ai) connect with a single "Connect"
click – the OAuth client_id/secret live on the server, not in each user's
config – because it implements Dynamic Client Registration on top of Google.
"""

from __future__ import annotations

import os

# Scope that makes the forwarded Google token usable against the Ads API.
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"

# Scopes requested at sign-in. ``openid``/``email`` identify the caller for
# logging; ``adwords`` is what lets us forward the token to the Ads API.
GOOGLE_SCOPES = ["openid", "email", ADWORDS_SCOPE]


def build_auth():
    """Construct the FastMCP ``GoogleProvider`` for the remote HTTP transport.

    Reads (all required for the remote HTTP transport):
      - ``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET`` – the OAuth
        client created in the deployer's own Google Cloud project.
      - ``RESOURCE_SERVER_URL`` – the public base URL of this server. Google's
        OAuth client must list ``<RESOURCE_SERVER_URL>/auth/callback`` as an
        authorized redirect URI.
    """
    from fastmcp.server.auth.providers.google import GoogleProvider

    try:
        client_id = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
        client_secret = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
        base_url = os.environ["RESOURCE_SERVER_URL"]
    except KeyError as missing:
        raise RuntimeError(
            f"The remote HTTP transport requires {missing}. Set "
            "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and "
            "RESOURCE_SERVER_URL."
        ) from missing

    return GoogleProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        required_scopes=GOOGLE_SCOPES,
    )
