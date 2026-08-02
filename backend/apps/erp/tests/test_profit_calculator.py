from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import Membership, Organization
from apps.erp.profit_calculator import calculate_profit, category_tree


class ProfitCalculatorTests(TestCase):
    def base_payload(self, **overrides):
        payload = {
            "country": "MY",
            "seller_type": "local",
            "shop_identity": "marketplace",
            "bxp": True,
            "delivered": True,
            "cny_per_myr": Decimal("1"),
            "usd_per_myr": Decimal("0.235"),
            "items": [{
                "sku_name": "帆布包",
                "category_code": "bag-womens-womens-tote-bags",
                "weight_g": Decimal("500"),
                "item_price": Decimal("18.98"),
                "product_cost_cny": Decimal("5.68"),
                "affiliate_rate": Decimal("10"),
            }],
        }
        payload.update(overrides)
        return payload

    def test_automatic_estimate_uses_sale_price_as_total_revenue(self):
        result = calculate_profit(self.base_payload())
        self.assertEqual(result["revenue"], "18.98")
        self.assertEqual(result["amount_summary"]["buyer_shipping_revenue"], "0.00")
        self.assertEqual(result["amount_summary"]["settlement_revenue"], "18.98")
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "0.00")

    def test_manual_fee_rate_is_supported(self):
        result = calculate_profit(self.base_payload(commission_rate_override=Decimal("10")))
        item = result["items"][0]
        self.assertEqual(item["fees"]["platform_commission"], "1.90")
        self.assertEqual(item["commission_rate_source"], "manual_override")

    def test_actual_settlement_amount_has_priority(self):
        payload = self.base_payload(commission_rate_override=Decimal("8"))
        payload["items"][0]["actual_platform_commission"] = Decimal("2.35")
        result = calculate_profit(payload)
        self.assertEqual(result["items"][0]["fees"]["platform_commission"], "2.35")
        self.assertEqual(result["items"][0]["commission_rate_source"], "actual_settlement")

    def test_transaction_fee_may_include_buyer_shipping_without_increasing_revenue(self):
        payload = self.base_payload()
        payload["items"][0]["buyer_shipping_paid"] = Decimal("2.00")
        result = calculate_profit(payload)
        self.assertEqual(result["revenue"], "18.98")
        self.assertEqual(result["items"][0]["transaction_base"], "20.98")
        self.assertEqual(result["items"][0]["fees"]["transaction_fee"], "0.79")

    def test_cross_border_shipping_uses_10g_rate_card_and_last_mile(self):
        west = calculate_profit(self.base_payload(seller_type="cross_border", destination_region="west_malaysia"))
        self.assertEqual(west["items"][0]["seller_shipping_cost"], "10.40")
        payload = self.base_payload(seller_type="cross_border", destination_region="east_malaysia")
        payload["items"][0]["weight_g"] = Decimal("501")
        east = calculate_profit(payload)
        self.assertEqual(east["items"][0]["chargeable_weight_g"], 510)
        self.assertEqual(east["items"][0]["seller_shipping_cost"], "15.65")

    def test_category_tree_remains_available(self):
        tree = category_tree()
        self.assertEqual([node["label"] for node in tree], ["箱包", "美妆个护"])


class ProfitCalculatorApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="calculator", password="test-pass-123")
        organization = Organization.objects.create(name="东铂", slug="profit-calculator")
        Membership.objects.create(organization=organization, user=self.user, role=Membership.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_config_returns_fee_configuration(self):
        response = self.client.get("/api/profit-calculator/config/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["transaction_rate"], "3.78")
        self.assertEqual(response.data["platform_support_fee"], "0.54")
        self.assertGreater(len(response.data["categories"]), 240)

    def test_calculate_accepts_manual_and_actual_fee_inputs(self):
        response = self.client.post("/api/profit-calculator/calculate/", {
            "country": "MY",
            "seller_type": "local",
            "shop_identity": "marketplace",
            "bxp": True,
            "cny_per_myr": "1.000000",
            "commission_rate_override": "10.00",
            "items": [{
                "category_code": "bag-womens-womens-tote-bags",
                "weight_g": "500.00",
                "item_price": "18.98",
                "product_cost_cny": "5.68",
                "affiliate_rate": "10.00",
                "actual_platform_commission": "2.35"
            }],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["revenue"], "18.98")
        self.assertEqual(response.data["items"][0]["fees"]["platform_commission"], "2.35")
