from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import Membership, Organization
from apps.erp.profit_calculator import calculate_profit, category_tree
from apps.erp.profit_shipping_rates import malaysia_cross_border_shipping


ECB_FIXTURE = b'''<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-07-29">
    <Cube currency="USD" rate="1.1600"/>
    <Cube currency="CNY" rate="8.4000"/>
    <Cube currency="MYR" rate="5.0000"/>
  </Cube></Cube>
</gesmes:Envelope>'''


class FakeRateResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return ECB_FIXTURE


class ProfitCalculatorTests(TestCase):
    def base_payload(self, **overrides):
        payload = {
            "country": "MY",
            "seller_type": "cross_border",
            "shop_identity": "marketplace",
            "bxp": False,
            "delivered": True,
            "commission_adjustment": Decimal("1.00"),
            "manual_commission_rate": None,
            "cny_per_myr": Decimal("1.68"),
            "usd_per_myr": Decimal("0.235"),
            "items": [{
                "sku_name": "帆布包",
                "category_code": "bag-womens-womens-tote-bags",
                "weight_g": Decimal("200"),
                "item_price": Decimal("79.90"),
                "product_cost_cny": Decimal("18.90"),
                "affiliate_rate": Decimal("15"),
            }],
        }
        payload.update(overrides)
        return payload

    def test_weight_drives_shipping_and_official_fee_bases(self):
        result = calculate_profit(self.base_payload())
        item = result["items"][0]
        self.assertEqual(item["rounded_weight_g"], 200)
        self.assertEqual(item["buyer_shipping_fee"], "0.00")
        self.assertEqual(item["seller_shipping_cost"], "3.00")
        self.assertEqual(item["commission_base"], "79.90")
        self.assertEqual(item["transaction_base"], "79.90")
        self.assertEqual(item["product_tax"], "7.26")
        self.assertEqual(item["affiliate_base"], "72.64")
        self.assertEqual(item["official_commission_rate"], "14.58")
        self.assertEqual(item["commission_rate"], "15.58")
        self.assertEqual(item["fees"]["platform_commission"], "12.45")
        self.assertEqual(item["fees"]["transaction_fee"], "3.02")
        self.assertEqual(item["fees"]["affiliate_commission"], "10.90")
        self.assertEqual(item["fees"]["product_cost"], "11.25")
        self.assertEqual(result["revenue"], "79.90")
        self.assertEqual(result["profit"], "38.74")
        self.assertEqual(result["profit_rate"], "48.49")
        self.assertEqual(result["break_even_cpa_usd"], "9.10")
        self.assertEqual(result["break_even_roi"], "2.06")
        self.assertEqual(result["gross_profit"], "38.74")
        self.assertIsNone(result["net_profit"])
        self.assertFalse(result["has_ad_cost"])
        self.assertEqual(result["amount_summary"], {
            "sales_revenue": "79.90",
            "buyer_shipping_revenue": "0.00",
            "settlement_revenue": "79.90",
            "platform_fees": "16.01",
            "affiliate_commission": "10.90",
            "logistics_cost": "3.00",
            "estimated_platform_payout": "49.99",
            "product_cost": "11.25",
            "gross_profit": "38.74",
            "advertising_cost": "0.00",
            "net_profit": None,
            "net_margin": None,
        })

    def test_weight_rounds_up_to_the_next_ten_gram_tier(self):
        payload = self.base_payload()
        payload["items"][0]["weight_g"] = Decimal("201")
        item = calculate_profit(payload)["items"][0]
        self.assertEqual(item["rounded_weight_g"], 210)
        self.assertEqual(item["seller_shipping_cost"], "3.15")

    def test_uploaded_shipping_price_list_examples(self):
        examples = {
            Decimal("180"): (180, Decimal("2.70")),
            Decimal("190"): (190, Decimal("2.85")),
            Decimal("200"): (200, Decimal("3.00")),
            Decimal("370"): (370, Decimal("5.55")),
        }
        for weight, expected in examples.items():
            with self.subTest(weight=weight):
                self.assertEqual(malaysia_cross_border_shipping(weight), expected)

    def test_shipping_does_not_extrapolate_beyond_price_list_limit(self):
        with self.assertRaisesRegex(ValueError, "30,000g"):
            malaysia_cross_border_shipping(Decimal("30000.01"))

    def test_local_store_does_not_apply_cross_border_lvg_tax(self):
        result = calculate_profit(self.base_payload(seller_type="local"))
        self.assertEqual(result["items"][0]["product_tax"], "0.00")
        self.assertEqual(result["items"][0]["affiliate_base"], "79.90")
        self.assertEqual(result["items"][0]["buyer_shipping_fee"], "0.00")
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "0.00")
        self.assertEqual(result["items"][0]["transaction_base"], "79.90")

    def test_actual_ad_roi_calculates_net_profit_only_when_provided(self):
        payload = self.base_payload()
        payload["items"][0]["ad_cost_type"] = "roi"
        payload["items"][0]["ad_cost_value"] = Decimal("4")
        result = calculate_profit(payload)
        self.assertEqual(result["advertising_cost"], "19.98")
        self.assertEqual(result["gross_profit"], "38.74")
        self.assertEqual(result["net_profit"], "18.76")
        self.assertEqual(result["net_margin"], "23.48")
        self.assertTrue(result["has_ad_cost"])

    def test_actual_cpa_usd_converts_to_myr(self):
        payload = self.base_payload()
        payload["items"][0]["ad_cost_type"] = "cpa_usd"
        payload["items"][0]["ad_cost_value"] = Decimal("5")
        result = calculate_profit(payload)
        self.assertEqual(result["advertising_cost"], "21.28")
        self.assertEqual(result["net_profit"], "17.46")

    def test_lvg_threshold_uses_tax_exclusive_rm500_value(self):
        payload = self.base_payload()
        payload["items"][0]["item_price"] = Decimal("550.00")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "50.00")
        payload["items"][0]["item_price"] = Decimal("550.01")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "0.00")

    def test_platform_support_fee_is_charged_per_sku(self):
        payload = self.base_payload()
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        result = calculate_profit(payload)
        support = next(row for row in result["breakdown"] if row["key"] == "platform_support_fee")
        self.assertEqual(support["amount"], "1.08")

    def test_essential_category_waives_platform_support_fee(self):
        payload = self.base_payload()
        payload["items"][0]["category_code"] = (
            "fmcg-food-and-beverages-staples-and-cooking-essentials"
        )
        result = calculate_profit(payload)
        support = next(row for row in result["breakdown"] if row["key"] == "platform_support_fee")
        self.assertEqual(support["amount"], "0.00")

    def test_bxp_fee_is_capped_at_rm54_per_item(self):
        payload = self.base_payload(bxp=True)
        payload["items"][0]["item_price"] = Decimal("2000")
        result = calculate_profit(payload)
        self.assertEqual(result["items"][0]["fees"]["bxp_fee"], "54.00")

    def test_terminal_beauty_category_inherits_official_group_rate(self):
        payload = self.base_payload()
        payload["items"][0]["category_code"] = "beauty-skincare-cleanser"
        item = calculate_profit(payload)["items"][0]
        self.assertEqual(item["category"], "美妆个护 / 护肤 / 洁面")
        self.assertEqual(item["official_commission_rate"], "15.12")
        self.assertEqual(item["commission_rate"], "16.12")

    def test_manual_commission_overrides_adjusted_official_rate(self):
        result = calculate_profit(self.base_payload(manual_commission_rate=Decimal("10")))
        item = result["items"][0]
        self.assertEqual(item["commission_rate"], "10")
        self.assertEqual(item["commission_rate_source"], "manual")
        self.assertEqual(item["fees"]["platform_commission"], "7.99")

    def test_zero_adjustment_restores_official_rate(self):
        result = calculate_profit(self.base_payload(commission_adjustment=Decimal("0")))
        self.assertEqual(result["items"][0]["commission_rate"], "14.58")

    def test_buyer_shipping_only_changes_transaction_fee_base(self):
        payload = self.base_payload()
        payload["items"][0]["buyer_shipping_fee"] = Decimal("2.00")
        result = calculate_profit(payload)
        item = result["items"][0]
        self.assertEqual(result["revenue"], "79.90")
        self.assertEqual(item["transaction_base"], "81.90")
        self.assertEqual(item["fees"]["transaction_fee"], "3.10")
        buyer_shipping = next(row for row in result["breakdown"] if row["key"] == "buyer_shipping_fee")
        self.assertTrue(buyer_shipping["exclude_from_group_total"])

    def test_breakdown_keeps_sales_first_and_sorts_groups_by_share(self):
        groups = calculate_profit(self.base_payload())["breakdown_groups"]
        self.assertEqual(groups[0]["key"], "收入")
        shares = [Decimal(group["share"]) for group in groups[1:] if Decimal(group["amount"]) > 0]
        self.assertEqual(shares, sorted(shares, reverse=True))
        logistics = next(group for group in groups if group["key"] == "物流")
        self.assertEqual([row["key"] for row in logistics["items"]], ["seller_shipping_cost", "buyer_shipping_fee"])

    def test_operator_tree_contains_complete_bag_and_beauty_groups(self):
        tree = category_tree()
        self.assertEqual([node["label"] for node in tree], ["箱包", "美妆个护"])
        bags, beauty = tree
        self.assertEqual(
            [node["label"] for node in bags["children"]],
            ["女包", "男包", "旅行箱包", "功能箱包", "箱包配件"],
        )
        self.assertEqual(len(beauty["children"]), 16)
        self.assertGreaterEqual(sum(len(node["children"]) for node in bags["children"]), 60)
        self.assertGreaterEqual(sum(len(node["children"]) for node in beauty["children"]), 120)


class ProfitCalculatorApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="calculator", password="test-pass-123")
        organization = Organization.objects.create(name="东铂", slug="profit-calculator")
        Membership.objects.create(organization=organization, user=self.user, role=Membership.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_config_returns_auditable_three_level_rules(self):
        response = self.client.get("/api/profit-calculator/config/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["transaction_rate"], "3.78")
        self.assertEqual(response.data["platform_support_fee"], "0.54")
        self.assertEqual(response.data["lvg_rate"], "10.00")
        self.assertEqual(response.data["default_commission_adjustment"], "1.00")
        self.assertEqual(response.data["shipping_rate_version"], "MY-CB-2026-05-15")
        self.assertEqual(response.data["shipping_max_weight_g"], "30000")
        self.assertGreater(len(response.data["categories"]), 240)
        self.assertEqual(
            [node["label"] for node in response.data["category_tree"]],
            ["箱包", "美妆个护"],
        )
        self.assertEqual(len(response.data["categories"][0]["path"]), 3)
        self.assertTrue(response.data["sources"]["lvg_tax"].startswith("https://mysst.customs.gov.my/"))

    def test_calculate_requires_weight(self):
        response = self.client.post("/api/profit-calculator/calculate/", {
            "country": "MY",
            "seller_type": "cross_border",
            "shop_identity": "marketplace",
            "cny_per_myr": "1.68",
            "items": [{
                "category_code": "bag-womens-womens-tote-bags",
                "item_price": "10.00",
            }],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("weight_g", response.data["items"][0])

    @patch("apps.erp.views.urlopen", return_value=FakeRateResponse())
    def test_exchange_rates_are_derived_from_one_ecb_daily_snapshot(self, mocked_urlopen):
        response = self.client.get("/api/profit-calculator/exchange-rates/?refresh=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["date"], "2026-07-29")
        self.assertEqual(response.data["cny_per_myr"], "1.680000")
        self.assertEqual(response.data["usd_per_myr"], "0.232000")
        self.assertEqual(response.data["source"], "European Central Bank")
        self.assertFalse(response.data["stale"])
        mocked_urlopen.assert_called_once()

    @patch("apps.erp.views.urlopen", side_effect=TimeoutError("upstream timeout"))
    def test_exchange_rates_return_last_good_snapshot_when_refresh_fails(self, mocked_urlopen):
        from django.core.cache import cache

        cache.set("profit-calculator:exchange-rates:ecb:last-good", {
            "date": "2026-07-28",
            "cny_per_myr": "1.670000",
            "usd_per_myr": "0.231000",
            "source": "European Central Bank",
            "source_url": "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            "stale": False,
        }, 60)
        response = self.client.get("/api/profit-calculator/exchange-rates/?refresh=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["date"], "2026-07-28")
        self.assertTrue(response.data["stale"])
        mocked_urlopen.assert_called_once()
