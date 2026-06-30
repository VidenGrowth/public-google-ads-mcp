"""Remote (HTTP) auth: a pure OAuth 2.0 Resource Server (RFC 9728).

The MCP client (e.g. Claude) obtains a Google token directly from Google; this
server only verifies it (``aud`` + ``adwords`` scope) and forwards it to the Ads
API (see ``google_ads/client.py``), so each user sees only their own accounts.
It runs no OAuth flow and holds no client secret – Google's OAuth client lists
the *client's* callbacks (e.g. ``https://claude.ai/api/mcp/auth_callback``) as
redirect URIs, not a URL on this server. No email allowlist.
"""

from __future__ import annotations

import os
import time

import httpx
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from pydantic import AnyHttpUrl

# Scope that lets the forwarded Google token reach the Ads API.
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"

# Advertised to clients at sign-in; only ``adwords`` is actually validated.
GOOGLE_SCOPES = ["openid", "email", ADWORDS_SCOPE]

# Authorization server advertised in protected-resource metadata.
GOOGLE_ISSUER = "https://accounts.google.com"

# Opaque Google tokens are validated here.
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
DEFAULT_CACHE_TTL_SECONDS = 300


class GoogleAdsTokenVerifier(TokenVerifier):
    """Verify opaque Google access tokens via Google's tokeninfo endpoint.

    Accepts a token only when it was issued to this server's OAuth client
    (``aud``), has a verified email, is unexpired, and carries the ``adwords``
    scope. Results are cached briefly (per-instance; safe to lose on restart).
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        super().__init__(required_scopes=[ADWORDS_SCOPE])
        self._client_id = client_id or os.environ["GOOGLE_OAUTH_CLIENT_ID"]
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[AccessToken, float]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.time()

        cached = self._cache.get(token)
        if cached is not None:
            access, expires_at = cached
            if expires_at > now:
                return access
            del self._cache[token]

        payload = await self._fetch_tokeninfo(token)
        if payload is None:
            return None

        # Only accept tokens minted for our OAuth client (anti confused-deputy).
        if payload.get("aud") != self._client_id:
            return None
        if payload.get("email_verified") not in ("true", True):
            return None

        granted: list[str] = str(payload.get("scope") or "").split()
        if ADWORDS_SCOPE not in granted:
            return None

        try:
            exp = int(payload["exp"])
        except (KeyError, TypeError, ValueError):
            return None
        if exp <= now:
            return None

        access = AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=granted,
            expires_at=exp,
            claims={
                "sub": payload.get("sub"),
                "email": (payload.get("email") or "").lower(),
            },
        )
        cache_until = min(now + self._cache_ttl, float(exp))
        self._cache[token] = (access, cache_until)
        return access

    async def _fetch_tokeninfo(self, token: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    GOOGLE_TOKENINFO_URL, params={"access_token": token}
                )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None


def build_auth():
    """Build the resource-server auth provider for the remote HTTP transport.

    Requires ``GOOGLE_OAUTH_CLIENT_ID`` (matched against each token's ``aud``)
    and ``RESOURCE_SERVER_URL`` (advertised in
    ``/.well-known/oauth-protected-resource``). No client secret lives here.
    """
    try:
        client_id = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
        base_url = os.environ["RESOURCE_SERVER_URL"]
    except KeyError as missing:
        raise RuntimeError(
            f"The remote HTTP transport requires {missing}. Set "
            "GOOGLE_OAUTH_CLIENT_ID and RESOURCE_SERVER_URL."
        ) from missing

    return RemoteAuthProvider(
        token_verifier=GoogleAdsTokenVerifier(client_id=client_id),
        authorization_servers=[AnyHttpUrl(GOOGLE_ISSUER)],
        base_url=base_url,
        scopes_supported=GOOGLE_SCOPES,
        resource_name="Google Ads MCP",
    )
