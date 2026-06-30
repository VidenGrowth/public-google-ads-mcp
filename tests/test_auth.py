from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google_ads_mcp import auth
from google_ads_mcp.google_ads import client as ads_client

# The resource server needs only the client id (for the ``aud`` check) and its
# own public URL. No OAuth client secret lives on the server anymore.
OAUTH_ENV = {
    "GOOGLE_OAUTH_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "RESOURCE_SERVER_URL": "https://mcp.example.com",
}


class BuildAuthTests(unittest.TestCase):
    def test_missing_env_raises(self):
        # Clear the required vars; build_auth must refuse to construct.
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                auth.build_auth()

    def test_builds_resource_server_without_secret(self):
        from fastmcp.server.auth import RemoteAuthProvider

        with patch.dict("os.environ", OAUTH_ENV, clear=True):
            provider = auth.build_auth()

        self.assertIsInstance(provider, RemoteAuthProvider)
        # Audience is bound to our OAuth client id.
        self.assertIsInstance(
            provider.token_verifier, auth.GoogleAdsTokenVerifier
        )
        self.assertEqual(
            provider.token_verifier._client_id,
            OAUTH_ENV["GOOGLE_OAUTH_CLIENT_ID"],
        )
        # Google is advertised as the authorization server.
        self.assertTrue(
            str(provider.authorization_servers[0]).startswith(auth.GOOGLE_ISSUER)
        )
        # adwords is the only scope we actually validate.
        self.assertEqual(
            provider.token_verifier.required_scopes, [auth.ADWORDS_SCOPE]
        )

    def test_scope_constant_includes_identity_and_adwords(self):
        self.assertIn("openid", auth.GOOGLE_SCOPES)
        self.assertIn("email", auth.GOOGLE_SCOPES)
        self.assertIn(auth.ADWORDS_SCOPE, auth.GOOGLE_SCOPES)


class GoogleAdsTokenVerifierTests(unittest.IsolatedAsyncioTestCase):
    """Token validation against a mocked Google tokeninfo response."""

    def _valid_payload(self) -> dict:
        return {
            "aud": "cid",
            "email_verified": "true",
            "email": "Alice@Example.com",
            "scope": f"openid email {auth.ADWORDS_SCOPE}",
            "exp": str(int(time.time()) + 3600),
        }

    async def _verify(self, payload):
        verifier = auth.GoogleAdsTokenVerifier(
            client_id="cid", cache_ttl_seconds=0
        )
        with patch.object(
            verifier, "_fetch_tokeninfo", AsyncMock(return_value=payload)
        ):
            return await verifier.verify_token("tok")

    async def test_accepts_valid_token(self):
        result = await self._verify(self._valid_payload())
        self.assertIsNotNone(result)
        self.assertIn(auth.ADWORDS_SCOPE, result.scopes)
        # email is normalized and exposed for observability.
        self.assertEqual(result.claims["email"], "alice@example.com")

    async def test_rejects_wrong_audience(self):
        payload = self._valid_payload()
        payload["aud"] = "someone-else.apps.googleusercontent.com"
        self.assertIsNone(await self._verify(payload))

    async def test_rejects_missing_adwords_scope(self):
        payload = self._valid_payload()
        payload["scope"] = "openid email"
        self.assertIsNone(await self._verify(payload))

    async def test_rejects_unverified_email(self):
        payload = self._valid_payload()
        payload["email_verified"] = "false"
        self.assertIsNone(await self._verify(payload))

    async def test_rejects_expired_token(self):
        payload = self._valid_payload()
        payload["exp"] = str(int(time.time()) - 1)
        self.assertIsNone(await self._verify(payload))

    async def test_rejects_when_tokeninfo_unavailable(self):
        self.assertIsNone(await self._verify(None))


class TokenForwardingFallbackTests(unittest.TestCase):
    """The stdio/local path must keep working when there is no OAuth context."""

    def setUp(self):
        ads_client._reset_client()

    def tearDown(self):
        ads_client._reset_client()

    def test_oauth_user_token_is_none_without_request_context(self):
        # No FastMCP request in scope → no forwarded token.
        self.assertIsNone(ads_client._oauth_user_token())

    def test_require_client_falls_back_to_credentials_singleton(self):
        sentinel = object()
        with patch.object(ads_client, "_oauth_user_token", return_value=None):
            with patch.object(
                ads_client, "get_google_ads_client", return_value=sentinel
            ):
                self.assertIs(ads_client.require_client(), sentinel)

    def test_require_client_raises_when_no_credentials(self):
        with patch.object(ads_client, "_oauth_user_token", return_value=None):
            with patch.object(
                ads_client, "get_google_ads_client", return_value=None
            ):
                with self.assertRaises(ads_client.ClientError):
                    ads_client.require_client()

    def test_oauth_token_gated_on_adwords_scope(self):
        # A token without the adwords scope must not be forwarded.
        no_scope = MagicMock(scopes=["openid", "email"], token="abc")
        with patch(
            "fastmcp.server.dependencies.get_access_token", return_value=no_scope
        ):
            self.assertIsNone(ads_client._oauth_user_token())

        with_scope = MagicMock(scopes=["openid", auth.ADWORDS_SCOPE], token="xyz")
        with patch(
            "fastmcp.server.dependencies.get_access_token", return_value=with_scope
        ):
            self.assertEqual(ads_client._oauth_user_token(), "xyz")


if __name__ == "__main__":
    unittest.main()
