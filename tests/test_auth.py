from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google_ads_mcp import auth
from google_ads_mcp.google_ads import client as ads_client

OAUTH_ENV = {
    "GOOGLE_OAUTH_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
    "RESOURCE_SERVER_URL": "https://mcp.example.com",
}


class BuildAuthTests(unittest.TestCase):
    def test_missing_env_raises(self):
        # Clear all three required vars; build_auth must refuse to construct.
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                auth.build_auth()

    def test_constructs_google_provider_with_adwords_scope(self):
        fake = MagicMock(name="GoogleProvider")
        with patch.dict("os.environ", OAUTH_ENV, clear=True):
            with patch(
                "fastmcp.server.auth.providers.google.GoogleProvider", fake
            ) as gp:
                auth.build_auth()
        gp.assert_called_once()
        kwargs = gp.call_args.kwargs
        self.assertEqual(kwargs["client_id"], OAUTH_ENV["GOOGLE_OAUTH_CLIENT_ID"])
        self.assertEqual(kwargs["client_secret"], OAUTH_ENV["GOOGLE_OAUTH_CLIENT_SECRET"])
        self.assertEqual(kwargs["base_url"], OAUTH_ENV["RESOURCE_SERVER_URL"])
        self.assertIn(auth.ADWORDS_SCOPE, kwargs["required_scopes"])

    def test_scope_constant_includes_identity_and_adwords(self):
        self.assertIn("openid", auth.GOOGLE_SCOPES)
        self.assertIn("email", auth.GOOGLE_SCOPES)
        self.assertIn(auth.ADWORDS_SCOPE, auth.GOOGLE_SCOPES)


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
