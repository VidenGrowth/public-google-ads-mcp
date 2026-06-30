"""Google Ads client initialization and query execution helpers."""

from __future__ import annotations

import os
import sys
from typing import Any

from google_ads_mcp.google_ads.utils import normalize_customer_id


class ClientError(Exception):
    """Raised when the Google Ads client cannot be initialized."""


# Module-level singleton – initialized once, reused across all tool calls.
_client = None


def get_google_ads_client():
    """Return the cached Google Ads API client, initializing it on first call.

    This is the credentials path used by local / stdio deployments. Resolution
    order:
      1. ``GOOGLE_ADS_CONFIGURATION_FILE_PATH`` – path to a google-ads.yaml file.
      2. ``GOOGLE_ADS_REFRESH_TOKEN`` (+ ``GOOGLE_ADS_DEVELOPER_TOKEN``,
         ``GOOGLE_ADS_CLIENT_ID``, ``GOOGLE_ADS_CLIENT_SECRET``) – installed-app
         OAuth using a refresh token you generate once with
         ``auth/generate_refresh_token.py``.

    ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` is optional and only needed when the
    caller wants the SDK to send a ``login-customer-id`` header (i.e. MCC
    impersonation). For directly-shared accounts it is omitted so the API
    authorizes against the OAuth user's direct grants.

    Returns ``None`` when no credentials are configured; callers should go
    through ``require_client()`` to surface a clear error instead.
    """
    global _client
    if _client is not None:
        return _client
    try:
        from google.ads.googleads.client import GoogleAdsClient

        config_path = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE_PATH")
        if config_path:
            _client = GoogleAdsClient.load_from_storage(config_path)
            return _client

        refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN")
        if refresh_token:
            credentials = {
                "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
                "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "use_proto_plus": True,
            }
            login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
            if login_customer_id:
                credentials["login_customer_id"] = login_customer_id
            _client = GoogleAdsClient.load_from_dict(credentials)
            return _client

        print(
            "Google Ads client not configured: set GOOGLE_ADS_CONFIGURATION_FILE_PATH, "
            "or GOOGLE_ADS_REFRESH_TOKEN together with GOOGLE_ADS_DEVELOPER_TOKEN, "
            "GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return None
    except Exception as exc:
        print(f"Failed to initialize Google Ads client: {exc}", file=sys.stderr)
        return None


def _reset_client() -> None:
    """Clear the cached client (useful for tests or credential rotation)."""
    global _client, _last_user_client
    _client = None
    _last_user_client = None


# Single-slot cache so a user's burst of calls within one request reuses the
# same per-user client instead of rebuilding it for every ``search_rows`` call.
_last_user_client: tuple[str, Any] | None = None


def _oauth_user_token() -> str | None:
    """Return the forwarded Google OAuth access token for the current request.

    Only meaningful under the remote HTTP transport: the resource server's
    token verifier validates the user's token on each request and exposes it
    (with the ``adwords`` scope) via ``get_access_token()``. Returns ``None``
    outside a request context (e.g. local stdio), so callers fall back to the
    configured credentials.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        from google_ads_mcp.auth import ADWORDS_SCOPE

        token = get_access_token()
    except Exception:
        return None
    if token is None:
        return None
    # Only forward tokens that actually carry Ads API access.
    if ADWORDS_SCOPE not in (getattr(token, "scopes", None) or []):
        return None
    return token.token


def _build_user_client(access_token: str):
    """Build a Google Ads client that authenticates as the OAuth user.

    The forwarded Google access token is used as the API credential; the
    server supplies only the developer token. No refresh token is needed –
    the token is already valid for the life of the request.
    """
    global _last_user_client
    if _last_user_client is not None and _last_user_client[0] == access_token:
        return _last_user_client[1]

    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials

    kwargs = {
        "credentials": Credentials(token=access_token),
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "use_proto_plus": True,
    }
    login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login_customer_id:
        kwargs["login_customer_id"] = login_customer_id
    client = GoogleAdsClient(**kwargs)
    _last_user_client = (access_token, client)
    return client


def require_client():
    """Return the Google Ads client for the current request, or raise.

    Prefers a per-user client built from the forwarded OAuth token (remote
    HTTP mode); otherwise falls back to the credentials-configured singleton
    (local stdio mode).
    """
    token = _oauth_user_token()
    if token:
        return _build_user_client(token)
    client = get_google_ads_client()
    if not client:
        raise ClientError("Google Ads client not configured. Set API credentials in environment variables.")
    return client


def search_rows(customer_id: str, query: str, login_customer_id: str | None = None) -> list[Any]:
    """Execute a streaming GAQL query and flatten the result rows.

    ``login_customer_id`` sets the ``login-customer-id`` header for this call
    only – pass the manager (MCC) ID to reach a *client* account through it.
    Omit it (``None``) to leave the client's configured value untouched (the
    normal path; honors ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` / the per-user client,
    and sends no header at all when none is configured). The override is
    applied per call and restored afterward, so it never leaks into later
    calls against the shared client singleton.
    """
    client = require_client()
    previous = client.login_customer_id
    if login_customer_id:
        client.login_customer_id = normalize_customer_id(login_customer_id)
    try:
        ga_service = client.get_service("GoogleAdsService")
        normalized_customer_id = normalize_customer_id(customer_id)
        rows = []
        for batch in ga_service.search_stream(customer_id=normalized_customer_id, query=query):
            rows.extend(batch.results)
        return rows
    finally:
        client.login_customer_id = previous


def manager_customer_id() -> str:
    """Return the configured MCC/login customer ID."""
    login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if not login_customer_id:
        client = get_google_ads_client()
        login_customer_id = getattr(client, "login_customer_id", None) if client else None
    if not login_customer_id:
        raise ClientError("GOOGLE_ADS_LOGIN_CUSTOMER_ID is not set.")
    return normalize_customer_id(str(login_customer_id))
