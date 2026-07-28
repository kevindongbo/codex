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
            "shop_identity": "marketplace",
            "bxp": False,
            "delivered": True,
            "cny_per_myr": Decimal("1.68"),
            "items": [{
                "sku_name": "帆布包",
                "category_code": "womens_bags",
                "quantity": Decimal("1"),
                "item_price": Decimal("79.90"),
                "seller_discount": Decimal("5.00"),
                "platform_discount": Decimal("3.00"),
                "product_tax": Decimal("0"),
                "buyer_shipping_fee": Decimal("4.90"),
                "product_cost_cny": Decimal("18.90"),
                "seller_shipping_cost": Decimal("3.00"),
                "affiliate_rate": Decimal("15"),
                "other_cost": Decimal("0"),
                "ad_spend": Decimal("0"),
            }],
        }
        payload.update(overrides)
        return payload

    def test_formula_uses_official_fee_bases_and_decimal_rounding(self):
        result = calculate_profit(self.base_payload())
        item = result["items"][0]
        self.assertEqual(item["commission_base"], "74.90")
        self.assertEqual(item["transaction_base"], "79.80")
        self.assertEqual(item["affiliate_base"], "71.90")
        self.assertEqual(item["fees"]["platform_commission"], "10.92")
        self.assertEqual(item["fees"]["transaction_fee"], "3.02")
        self.assertEqual(item["fees"]["affiliate_commission"], "10.79")
        self.assertEqual(item["fees"]["product_cost"], "11.25")
        self.assertEqual(result["revenue"], "79.80")
        self.assertEqual(result["profit"], "40.28")
        self.assertEqual(result["profit_rate"], "50.48")

    def test_platform_support_fee_is_charged_once_for_multiple_skus(self):
        payload = self.base_payload()
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        result = calculate_profit(payload)
        support = next(row for row in result["breakdown"] if row["key"] == "platform_support_fee")
        self.assertEqual(support["amount"], "0.54")

    def test_bxp_uses_lower_commission_plus_bxp_fee(self):
        payload = self.base_payload(bxp=True)
        result = calculate_profit(payload)
        item = result["items"][0]
        self.assertEqual(item["commission_rate"], "10.26")
        self.assertEqual(item["fees"]["bxp_fee"], "3.64")


class ProfitCalculatorApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="calculator", password="test-pass-123")
        organization = Organization.objects.create(name="东铂", slug="profit-calculator")
        Membership.objects.create(organization=organization, user=self.user, role=Membership.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_config_returns_auditable_rules(self):
        response = self.client.get("/api/profit-calculator/config/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["transaction_rate"], "3.78")
        self.assertEqual(response.data["platform_support_fee"], "0.54")
        self.assertTrue(response.data["sources"]["commission"].startswith("https://seller-my.tiktok.com/"))

    def test_calculate_rejects_custom_category_without_rate(self):
        response = self.client.post("/api/profit-calculator/calculate/", {
            "country": "MY",
            "shop_identity": "marketplace",
            "cny_per_myr": "1.68",
            "items": [{"category_code": "custom", "item_price": "10.00"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_commission_rate", response.data["items"][0])
