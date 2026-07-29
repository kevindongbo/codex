from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import Membership, Organization
from apps.erp.profit_calculator import calculate_profit


class ProfitCalculatorTests(TestCase):
    def base_payload(self, **overrides):
        payload = {
            "country": "MY",
            "seller_type": "cross_border",
            "shop_identity": "marketplace",
            "bxp": False,
            "delivered": True,
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
        self.assertEqual(item["shipping_tier_kg"], 1)
        self.assertEqual(item["buyer_shipping_fee"], "2.90")
        self.assertEqual(item["seller_shipping_cost"], "2.90")
        self.assertEqual(item["commission_base"], "79.90")
        self.assertEqual(item["transaction_base"], "82.80")
        self.assertEqual(item["product_tax"], "7.26")
        self.assertEqual(item["affiliate_base"], "72.64")
        self.assertEqual(item["fees"]["platform_commission"], "11.65")
        self.assertEqual(item["fees"]["transaction_fee"], "3.13")
        self.assertEqual(item["fees"]["affiliate_commission"], "10.90")
        self.assertEqual(item["fees"]["product_cost"], "11.25")
        self.assertEqual(result["revenue"], "82.80")
        self.assertEqual(result["profit"], "42.43")
        self.assertEqual(result["profit_rate"], "51.24")
        self.assertEqual(result["break_even_cpa_usd"], "9.97")
        self.assertEqual(result["break_even_roi"], "1.95")
        self.assertEqual(result["gross_profit"], "42.43")
        self.assertIsNone(result["net_profit"])
        self.assertFalse(result["has_ad_cost"])

    def test_weight_rounds_up_to_the_next_official_kg_tier(self):
        payload = self.base_payload()
        payload["items"][0]["weight_g"] = Decimal("1001")
        item = calculate_profit(payload)["items"][0]
        self.assertEqual(item["shipping_tier_kg"], 2)
        self.assertEqual(item["seller_shipping_cost"], "2.90")

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
        self.assertEqual(result["advertising_cost"], "20.70")
        self.assertEqual(result["gross_profit"], "42.43")
        self.assertEqual(result["net_profit"], "21.73")
        self.assertEqual(result["net_margin"], "26.24")
        self.assertTrue(result["has_ad_cost"])

    def test_actual_cpa_usd_converts_to_myr(self):
        payload = self.base_payload()
        payload["items"][0]["ad_cost_type"] = "cpa_usd"
        payload["items"][0]["ad_cost_value"] = Decimal("5")
        result = calculate_profit(payload)
        self.assertEqual(result["advertising_cost"], "21.28")
        self.assertEqual(result["net_profit"], "21.15")

    def test_lvg_threshold_uses_tax_exclusive_rm500_value(self):
        payload = self.base_payload()
        payload["items"][0]["item_price"] = Decimal("550.00")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "50.00")
        payload["items"][0]["item_price"] = Decimal("550.01")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "0.00")

    def test_platform_support_fee_is_charged_once_for_multiple_skus(self):
        payload = self.base_payload()
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        result = calculate_profit(payload)
        support = next(row for row in result["breakdown"] if row["key"] == "platform_support_fee")
        self.assertEqual(support["amount"], "0.54")

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
        self.assertGreater(len(response.data["categories"]), 240)
        self.assertTrue(response.data["category_tree"])
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
