from decimal import Decimal

from django.test import SimpleTestCase

from apps.erp.profit_calculator import calculate_profit


class ProfitFeeRulesV5Tests(SimpleTestCase):
    def payload(self, **overrides):
        data = {
            "seller_type": "local",
            "shop_identity": "marketplace",
            "bxp": True,
            "delivered": True,
            "cny_per_myr": Decimal("1"),
            "usd_per_myr": Decimal("0.235"),
            "items": [{
                "sku_name": "测试包",
                "category_code": "bag-womens-womens-tote-bags",
                "weight_g": Decimal("500"),
                "item_price": Decimal("18.98"),
                "product_cost_cny": Decimal("5.68"),
                "affiliate_rate": Decimal("10"),
            }],
        }
        data.update(overrides)
        return data

    def test_total_revenue_excludes_buyer_shipping(self):
        payload = self.payload()
        payload["items"][0]["buyer_shipping_paid"] = Decimal("2")
        result = calculate_profit(payload)
        self.assertEqual(result["revenue"], "18.98")
        self.assertEqual(result["items"][0]["transaction_base"], "20.98")
        self.assertEqual(result["items"][0]["fees"]["transaction_fee"], "0.79")

    def test_manual_commission_rate_controls_estimate(self):
        payload = self.payload(commission_rate_override=Decimal("10"))
        result = calculate_profit(payload)
        item = result["items"][0]
        self.assertEqual(item["fees"]["platform_commission"], "1.90")
        self.assertEqual(item["commission_rate_source"], "manual_override")

    def test_actual_commission_wins_without_rewriting_official_rate(self):
        payload = self.payload(commission_rate_override=Decimal("8"))
        payload["items"][0]["actual_platform_commission"] = Decimal("2.35")
        result = calculate_profit(payload)
        item = result["items"][0]
        self.assertEqual(item["fees"]["platform_commission"], "2.35")
        self.assertEqual(item["commission_rate_source"], "actual_settlement")
        commission = next(row for row in result["breakdown"] if row["key"] == "platform_commission")
        self.assertEqual(commission["share"], "12.38")

    def test_local_shipping_is_zero(self):
        result = calculate_profit(self.payload())
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "0.00")

    def test_cross_border_west_500g_is_complete_merchant_cost(self):
        result = calculate_profit(self.payload(seller_type="cross_border", destination_region="west_malaysia"))
        self.assertEqual(result["items"][0]["chargeable_weight_g"], 500)
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "10.40")

    def test_cross_border_east_501g_rounds_to_510g(self):
        payload = self.payload(seller_type="cross_border", destination_region="east_malaysia")
        payload["items"][0]["weight_g"] = Decimal("501")
        result = calculate_profit(payload)
        self.assertEqual(result["items"][0]["chargeable_weight_g"], 510)
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "15.65")

    def test_actual_shipping_wins_over_rate_card(self):
        payload = self.payload(seller_type="cross_border")
        payload["items"][0]["actual_seller_shipping_cost"] = Decimal("1.80")
        result = calculate_profit(payload)
        self.assertEqual(result["items"][0]["seller_shipping_cost"], "1.80")
        shipping = next(row for row in result["breakdown"] if row["key"] == "seller_shipping_cost")
        self.assertEqual(shipping["source_type"], "actual_settlement")
