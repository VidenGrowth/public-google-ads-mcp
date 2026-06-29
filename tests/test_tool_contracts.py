from __future__ import annotations

import asyncio
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from google.ads.googleads.v23.services.types.google_ads_service import GoogleAdsRow

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google_ads_mcp.tools import accounts, diagnostics, query, reporting

_CUSTOMER_STATUS_ENABLED = 2  # CustomerStatusEnum.CustomerStatus.ENABLED


_META_RE = re.compile(r"<meta>(.*?)</meta>", re.DOTALL)
_DATA_RE = re.compile(r"<data>\n(.*?)\n</data>", re.DOTALL)
_ERROR_RE = re.compile(r"<error>(.*?)</error>", re.DOTALL)


def _parse_table(result: str) -> tuple[dict, list[str], list[list[str]]]:
    """Parse a <meta>+<data> tool response into (meta, header, rows)."""
    m = _META_RE.search(result)
    assert m, f"missing <meta> block in: {result!r}"
    meta = json.loads(m.group(1))
    d = _DATA_RE.search(result)
    if not d:
        return meta, [], []
    body_lines = d.group(1).split("\n")
    header = body_lines[0].split("\t")
    rows = [line.split("\t") for line in body_lines[1:]]
    return meta, header, rows


def _parse_error(result: str) -> dict:
    m = _ERROR_RE.search(result)
    assert m, f"missing <error> block in: {result!r}"
    return json.loads(m.group(1))


class ToolContractTests(unittest.TestCase):
    def test_row_to_flat_preserves_numeric_scalars_without_guessing_text(self) -> None:
        row = GoogleAdsRow()
        row.campaign.id = 23602215258
        row.campaign.name = "123"
        row.metrics.clicks = 211
        row.metrics.conversions_value = 12.5

        flat = query._row_to_flat(row)

        self.assertEqual(flat["campaign.id"], 23602215258)
        self.assertIsInstance(flat["campaign.id"], int)
        self.assertEqual(flat["campaign.name"], "123")
        self.assertIsInstance(flat["campaign.name"], str)
        self.assertEqual(flat["metrics.clicks"], 211)
        self.assertIsInstance(flat["metrics.clicks"], int)
        self.assertEqual(flat["metrics.conversions_value"], 12.5)
        self.assertIsInstance(flat["metrics.conversions_value"], float)

    def test_keyword_quality_defaults_to_worst_first(self) -> None:
        with patch("google_ads_mcp.tools.diagnostics.search_rows", return_value=[]) as search_rows:
            diagnostics.get_keyword_quality_details(customer_id="1234567890")

        query = search_rows.call_args.args[1]
        self.assertIn("ORDER BY ad_group_criterion.quality_info.quality_score ASC", query)

    def test_budget_pacing_empty_month_uses_table_shape(self) -> None:
        with patch(
            "google_ads_mcp.tools.diagnostics.today_month_context",
            return_value=(date(2026, 5, 1), date(2026, 4, 30), 31),
        ):
            result = diagnostics.get_budget_pacing(customer_id="1234567890")

        meta, _, _ = _parse_table(result)
        self.assertEqual(meta["applied"]["row_count"], 0)
        self.assertEqual(meta["month_start"], "2026-05-01")
        self.assertEqual(meta["through_date"], None)

    def test_daily_performance_by_campaign_excludes_removed_campaigns_by_default(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_daily_performance_by_campaign(customer_id="1234567890")

        query = search_rows.call_args.args[1]
        self.assertIn("campaign.status != 'REMOVED'", query)
        self.assertIn("campaign.id", query)
        self.assertIn("campaign.name", query)

    def test_daily_performance_aggregates_across_campaigns(self) -> None:
        row_a = GoogleAdsRow()
        row_a.segments.date = "2026-04-01"
        row_a.campaign.id = 111
        row_a.metrics.impressions = 100
        row_a.metrics.clicks = 10
        row_a.metrics.cost_micros = 1_000_000
        row_a.metrics.conversions = 2
        row_a.metrics.conversions_value = 20.0

        row_b = GoogleAdsRow()
        row_b.segments.date = "2026-04-01"
        row_b.campaign.id = 222
        row_b.metrics.impressions = 50
        row_b.metrics.clicks = 5
        row_b.metrics.cost_micros = 500_000
        row_b.metrics.conversions = 1
        row_b.metrics.conversions_value = 5.0

        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[row_a, row_b]):
            result = reporting.get_daily_performance(customer_id="1234567890")

        meta, header, rows = _parse_table(result)
        self.assertEqual(meta["applied"]["row_count"], 1)
        self.assertNotIn("campaign_id", header)
        values = dict(zip(header, rows[0]))
        self.assertEqual(values["date"], "2026-04-01")
        self.assertEqual(int(values["impressions"]), 150)
        self.assertEqual(int(values["clicks"]), 15)
        self.assertAlmostEqual(float(values["cost"]), 1.5)
        self.assertAlmostEqual(float(values["conversions"]), 3.0)
        self.assertAlmostEqual(float(values["conversion_value"]), 25.0)

    def test_conversion_breakdown_excludes_cost_metrics(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_conversion_breakdown_by_campaign(customer_id="1234567890")

        query = search_rows.call_args.args[1]
        self.assertNotIn("metrics.cost_micros", query)
        self.assertNotIn("metrics.impressions", query)
        self.assertNotIn("metrics.clicks", query)
        self.assertIn("segments.conversion_action", query)
        self.assertIn("metrics.conversions_by_conversion_date", query)
        self.assertIn("metrics.all_conversions", query)

    def test_conversion_breakdown_overall_aggregates_across_campaigns(self) -> None:
        action_resource = "customers/1234567890/conversionActions/987"

        row_a = GoogleAdsRow()
        row_a.campaign.id = 111
        row_a.segments.conversion_action = action_resource
        row_a.segments.conversion_action_name = "Purchase"
        row_a.metrics.conversions = 4
        row_a.metrics.conversions_value = 40.0
        row_a.metrics.all_conversions = 5
        row_a.metrics.all_conversions_value = 50.0

        row_b = GoogleAdsRow()
        row_b.campaign.id = 222
        row_b.segments.conversion_action = action_resource
        row_b.segments.conversion_action_name = "Purchase"
        row_b.metrics.conversions = 3
        row_b.metrics.conversions_value = 30.0
        row_b.metrics.all_conversions = 3
        row_b.metrics.all_conversions_value = 30.0

        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[row_a, row_b]):
            result = reporting.get_conversion_breakdown_overall(customer_id="1234567890")

        meta, header, rows = _parse_table(result)
        self.assertEqual(meta["applied"]["row_count"], 1)
        self.assertEqual(meta["group_level"], "overall")
        values = dict(zip(header, rows[0]))
        self.assertEqual(values["conversion_action_id"], "987")
        self.assertEqual(values["conversion_action_name"], "Purchase")
        self.assertAlmostEqual(float(values["conversions"]), 7.0)
        self.assertAlmostEqual(float(values["conversion_value"]), 70.0)
        self.assertAlmostEqual(float(values["all_conversions"]), 8.0)
        self.assertAlmostEqual(float(values["all_conversions_value"]), 80.0)

    def test_daily_conversion_breakdown_aggregates_across_campaigns(self) -> None:
        action_resource = "customers/1234567890/conversionActions/42"

        row_a = GoogleAdsRow()
        row_a.segments.date = "2026-04-01"
        row_a.campaign.id = 111
        row_a.segments.conversion_action = action_resource
        row_a.segments.conversion_action_name = "Lead"
        row_a.metrics.conversions = 2
        row_a.metrics.conversions_value = 10.0
        row_a.metrics.conversions_by_conversion_date = 1
        row_a.metrics.conversions_value_by_conversion_date = 5.0

        row_b = GoogleAdsRow()
        row_b.segments.date = "2026-04-01"
        row_b.campaign.id = 222
        row_b.segments.conversion_action = action_resource
        row_b.segments.conversion_action_name = "Lead"
        row_b.metrics.conversions = 3
        row_b.metrics.conversions_value = 15.0
        row_b.metrics.conversions_by_conversion_date = 2
        row_b.metrics.conversions_value_by_conversion_date = 10.0

        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[row_a, row_b]):
            result = reporting.get_daily_conversion_breakdown(customer_id="1234567890")

        meta, header, rows = _parse_table(result)
        self.assertEqual(meta["applied"]["row_count"], 1)
        self.assertEqual(meta["group_level"], "daily")
        values = dict(zip(header, rows[0]))
        self.assertEqual(values["date"], "2026-04-01")
        self.assertEqual(values["conversion_action_id"], "42")
        self.assertAlmostEqual(float(values["conversions"]), 5.0)
        self.assertAlmostEqual(float(values["conversions_by_conversion_date"]), 3.0)
        self.assertAlmostEqual(float(values["conversion_value_by_conversion_date"]), 15.0)

    def test_device_performance_accepts_campaign_status_filters(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_device_performance(
                customer_id="1234567890",
                campaign_status="PAUSED",
                campaign_primary_status="ELIGIBLE",
            )

        query = search_rows.call_args.args[1]
        self.assertIn("campaign.status = 'PAUSED'", query)
        self.assertIn("campaign.primary_status = 'ELIGIBLE'", query)

    def test_age_performance_excludes_removed_campaigns_and_ad_groups(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_age_by_campaign(customer_id="1234567890")

        query = search_rows.call_args.args[1]
        self.assertIn("campaign.status != 'REMOVED'", query)
        self.assertIn("ad_group.status != 'REMOVED'", query)

    def test_keyword_aggregate_limit_validation_matches_other_tools(self) -> None:
        result = reporting.get_keywords_overall(customer_id="1234567890", limit=0)

        self.assertEqual(_parse_error(result), {"error": "limit must be greater than 0."})

    def test_asset_group_text_assets_filters_field_types(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_asset_group_text_assets(customer_id="1234567890")

        q = search_rows.call_args.args[1]
        self.assertIn(
            "asset_group_asset.field_type IN ('HEADLINE', 'LONG_HEADLINE', 'DESCRIPTION')",
            q,
        )
        self.assertIn("campaign.status != 'REMOVED'", q)
        self.assertIn("asset_group.status != 'REMOVED'", q)

    def test_asset_group_video_assets_single_field_type(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_asset_group_video_assets(customer_id="1234567890")

        q = search_rows.call_args.args[1]
        self.assertIn("asset_group_asset.field_type = 'YOUTUBE_VIDEO'", q)
        self.assertIn("asset.youtube_video_asset.youtube_video_id", q)

    def test_asset_group_image_assets_covers_all_image_field_types(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_asset_group_image_assets(customer_id="1234567890")

        q = search_rows.call_args.args[1]
        for field_type in (
            "MARKETING_IMAGE",
            "SQUARE_MARKETING_IMAGE",
            "PORTRAIT_MARKETING_IMAGE",
            "LOGO",
            "LANDSCAPE_LOGO",
        ):
            self.assertIn(f"'{field_type}'", q)
        self.assertIn("asset.image_asset.full_size.width_pixels", q)

    def test_asset_group_text_assets_field_type_subset_filter(self) -> None:
        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[]) as search_rows:
            reporting.get_asset_group_text_assets(
                customer_id="1234567890",
                field_type="HEADLINE",
            )

        q = search_rows.call_args.args[1]
        self.assertIn("asset_group_asset.field_type = 'HEADLINE'", q)
        self.assertNotIn("LONG_HEADLINE", q)

    def test_asset_group_text_assets_rejects_invalid_field_type(self) -> None:
        result = reporting.get_asset_group_text_assets(
            customer_id="1234567890",
            field_type="YOUTUBE_VIDEO",
        )
        self.assertIn("Invalid field_type value(s)", _parse_error(result)["error"])

    def test_accessible_accounts_expands_manager_seeds(self) -> None:
        def seed_row(cid: int, *, manager: bool) -> GoogleAdsRow:
            row = GoogleAdsRow()
            row.customer.id = cid
            row.customer.descriptive_name = f"Account {cid}"
            row.customer.currency_code = "USD"
            row.customer.time_zone = "America/New_York"
            row.customer.status = _CUSTOMER_STATUS_ENABLED
            row.customer.manager = manager
            return row

        def child_row(cid: int, level: int) -> GoogleAdsRow:
            row = GoogleAdsRow()
            row.customer_client.id = cid
            row.customer_client.descriptive_name = f"Client {cid}"
            row.customer_client.currency_code = "USD"
            row.customer_client.time_zone = "America/New_York"
            row.customer_client.status = _CUSTOMER_STATUS_ENABLED
            row.customer_client.manager = False
            row.customer_client.level = level
            return row

        # Seed 111 is a manager with two ENABLED sub-accounts; seed 222 is a
        # directly-shared leaf.
        seeds = {"1111111111": True, "2222222222": False}
        children = [child_row(3333333333, 1), child_row(4444444444, 2)]

        def fake_search_rows(customer_id, query, login_customer_id=None):
            if "FROM customer_client" in query:
                return children
            return [seed_row(int(customer_id), manager=seeds[customer_id])]

        fake_client = unittest.mock.MagicMock()
        fake_client.get_service.return_value.list_accessible_customers.return_value.resource_names = [
            "customers/1111111111",
            "customers/2222222222",
        ]

        with patch("google_ads_mcp.tools.accounts.require_client", return_value=fake_client), patch(
            "google_ads_mcp.tools.accounts.search_rows", side_effect=fake_search_rows
        ):
            result = asyncio.run(accounts.get_accessible_accounts())

        meta, header, rows = _parse_table(result)
        self.assertEqual(meta["applied"]["row_count"], 4)
        self.assertEqual(meta["seed_accounts"], 2)

        by_id = {r[header.index("customer_id")]: dict(zip(header, r)) for r in rows}
        # Manager seed and leaf seed are level 0 with no parent.
        self.assertEqual(by_id["1111111111"]["level"], "0")
        self.assertEqual(by_id["1111111111"]["is_manager"], "true")
        self.assertEqual(by_id["1111111111"]["manager_customer_id"], "")
        self.assertEqual(by_id["2222222222"]["level"], "0")
        # Sub-accounts are attributed to the manager seed they were found under.
        self.assertEqual(by_id["3333333333"]["level"], "1")
        self.assertEqual(by_id["3333333333"]["manager_customer_id"], "1111111111")
        self.assertEqual(by_id["4444444444"]["level"], "2")
        self.assertEqual(by_id["4444444444"]["manager_customer_id"], "1111111111")

    def test_accessible_accounts_merge_is_deterministic_across_managers(self) -> None:
        # Two manager seeds whose subtrees both contain account 9999999999.
        # Whichever query returns first, the shared child must be attributed to
        # the first manager in seed order (deterministic merge), not the one
        # whose thread happens to finish first.
        def seed_row(cid: int) -> GoogleAdsRow:
            row = GoogleAdsRow()
            row.customer.id = cid
            row.customer.descriptive_name = f"MCC {cid}"
            row.customer.status = _CUSTOMER_STATUS_ENABLED
            row.customer.manager = True
            return row

        def child_row(cid: int) -> GoogleAdsRow:
            row = GoogleAdsRow()
            row.customer_client.id = cid
            row.customer_client.descriptive_name = f"Client {cid}"
            row.customer_client.status = _CUSTOMER_STATUS_ENABLED
            row.customer_client.manager = False
            row.customer_client.level = 1
            return row

        shared = child_row(9999999999)
        subtrees = {
            "1111111111": [shared],
            "2222222222": [shared],
        }

        def fake_search_rows(customer_id, query, login_customer_id=None):
            if "FROM customer_client" in query:
                return subtrees[customer_id]
            return [seed_row(int(customer_id))]

        fake_client = unittest.mock.MagicMock()
        fake_client.get_service.return_value.list_accessible_customers.return_value.resource_names = [
            "customers/1111111111",
            "customers/2222222222",
        ]

        with patch("google_ads_mcp.tools.accounts.require_client", return_value=fake_client), patch(
            "google_ads_mcp.tools.accounts.search_rows", side_effect=fake_search_rows
        ):
            result = asyncio.run(accounts.get_accessible_accounts())

        _, header, rows = _parse_table(result)
        by_id = {r[header.index("customer_id")]: dict(zip(header, r)) for r in rows}
        self.assertEqual(by_id["9999999999"]["manager_customer_id"], "1111111111")

    def test_output_format_uses_xml_envelope(self) -> None:
        row = GoogleAdsRow()
        row.segments.date = "2026-04-01"
        row.campaign.id = 111
        row.metrics.impressions = 100
        row.metrics.clicks = 10
        row.metrics.cost_micros = 1_000_000
        row.metrics.conversions = 2
        row.metrics.conversions_value = 20.0

        with patch("google_ads_mcp.tools.reporting.search_rows", return_value=[row]):
            result = reporting.get_daily_performance(customer_id="1234567890")

        self.assertTrue(result.startswith("<meta>"), result[:40])
        self.assertIn("</meta>", result)
        self.assertIn("<data>", result)
        self.assertTrue(result.endswith("</data>"), result[-40:])

        meta, header, rows = _parse_table(result)
        self.assertIn("applied", meta)
        self.assertIn("date_range", meta["applied"])
        self.assertIn("row_count", meta["applied"])
        self.assertEqual(meta["applied"]["row_count"], len(rows))
        self.assertGreater(len(header), 0)


if __name__ == "__main__":
    unittest.main()
