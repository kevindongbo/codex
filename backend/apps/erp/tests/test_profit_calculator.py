from decimal import Decimal
from dataclasses import replace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.erp.models import AuditLog, ExchangeRateSnapshot, Membership, Organization, ProfitCalculationStrategy
from apps.erp.exchange_rates import refresh_snapshot
from apps.erp.profit_calculator import CATEGORY_RULES, calculate_profit, category_tree
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


class FakePayloadResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


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
        self.assertEqual(result["total_fees"], "37.17")
        self.assertEqual(result["settlement_amount"], "42.73")
        self.assertEqual(result["profit"], "31.48")
        self.assertEqual(result["profit_rate"], "39.40")
        self.assertEqual(result["break_even_cpa_usd"], "7.40")
        self.assertEqual(result["break_even_roi"], "2.54")
        self.assertEqual(result["gross_profit"], "31.48")
        self.assertIsNone(result["net_profit"])
        self.assertFalse(result["has_ad_cost"])
        self.assertEqual(result["amount_summary"]["total_revenue"], "79.90")
        self.assertEqual(result["amount_summary"]["total_fees"], "37.17")
        self.assertEqual(result["amount_summary"]["costs_before_ads"], "48.42")

    def test_weight_rounds_up_to_the_next_ten_gram_tier(self):
        payload = self.base_payload()
        payload["items"][0]["weight_g"] = Decimal("181")
        item = calculate_profit(payload)["items"][0]
        self.assertEqual(item["rounded_weight_g"], 190)
        self.assertEqual(item["seller_shipping_cost"], "2.85")

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
        self.assertEqual(malaysia_cross_border_shipping(Decimal("30000")), (30000, Decimal("450.00")))
        with self.assertRaisesRegex(ValueError, "超过当前运费价表范围"):
            malaysia_cross_border_shipping(Decimal("30001"))

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
        self.assertEqual(result["gross_profit"], "31.48")
        self.assertEqual(result["net_profit"], "11.50")
        self.assertEqual(result["net_margin"], "14.39")
        self.assertTrue(result["has_ad_cost"])

    def test_actual_cpa_usd_converts_to_myr(self):
        payload = self.base_payload()
        payload["items"][0]["ad_cost_type"] = "cpa_usd"
        payload["items"][0]["ad_cost_value"] = Decimal("5")
        result = calculate_profit(payload)
        self.assertEqual(result["advertising_cost"], "21.28")
        self.assertEqual(result["net_profit"], "10.20")

    def test_lvg_threshold_uses_original_single_item_price(self):
        payload = self.base_payload()
        payload["items"][0]["item_price"] = Decimal("500.00")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "45.45")
        payload["items"][0]["item_price"] = Decimal("550.01")
        self.assertEqual(calculate_profit(payload)["items"][0]["product_tax"], "0.00")

    def test_platform_support_fee_is_charged_once_per_delivered_order_and_allocated(self):
        payload = self.base_payload()
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        result = calculate_profit(payload)
        support = next(row for row in result["breakdown"] if row["key"] == "platform_support_fee")
        self.assertEqual(support["amount"], "0.54")
        self.assertEqual(
            [item["fees"]["platform_support_fee"] for item in result["items"]],
            ["0.27", "0.27"],
        )

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

    def test_manual_commission_overrides_only_its_sku_and_clearing_restores_auto(self):
        payload = self.base_payload()
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        payload["items"][0]["manual_commission_rate"] = Decimal("10")
        result = calculate_profit(payload)
        self.assertEqual(result["items"][0]["commission_rate"], "10")
        self.assertEqual(result["items"][0]["commission_rate_source"], "manual")
        self.assertEqual(result["items"][1]["commission_rate"], "15.58")
        self.assertEqual(result["items"][1]["commission_rate_source"], "official_adjusted")
        del payload["items"][0]["manual_commission_rate"]
        self.assertEqual(calculate_profit(payload)["items"][0]["commission_rate"], "15.58")

    def test_zero_adjustment_restores_official_rate(self):
        result = calculate_profit(self.base_payload(commission_adjustment=Decimal("0")))
        self.assertEqual(result["items"][0]["commission_rate"], "14.58")

    @patch("apps.erp.profit_calculator.resolve_category")
    def test_missing_official_commission_requires_a_manual_rate(self, mocked_resolve_category):
        original = CATEGORY_RULES["bag-womens-womens-tote-bags"]
        mocked_resolve_category.return_value = replace(
            original,
            marketplace_bxp=None,
            marketplace_standard=None,
            mall_bxp=None,
            mall_standard=None,
        )
        with self.assertRaisesRegex(ValueError, "没有官方佣金率"):
            calculate_profit(self.base_payload())
        payload = self.base_payload()
        payload["items"][0]["manual_commission_rate"] = Decimal("10")
        self.assertEqual(calculate_profit(payload)["items"][0]["commission_rate"], "10")

    def test_buyer_shipping_is_order_level_and_only_changes_transaction_fee_base(self):
        payload = self.base_payload()
        payload["buyer_pays_shipping"] = True
        payload["buyer_shipping_region"] = "west_malaysia"
        result = calculate_profit(payload)
        item = result["items"][0]
        self.assertEqual(result["revenue"], "79.90")
        self.assertEqual(item["transaction_base"], "82.80")
        self.assertEqual(result["transaction_fee"]["amount"], "3.13")
        self.assertEqual(result["shipping"]["buyer_shipping_amount"], "2.90")
        buyer_shipping = next(row for row in result["breakdown"] if row["key"] == "buyer_shipping_fee")
        self.assertTrue(buyer_shipping["exclude_from_group_total"])

    def test_buyer_shipping_is_reference_only_and_follows_logistics_sorting(self):
        payload = self.base_payload()
        payload["buyer_pays_shipping"] = True
        result = calculate_profit(payload)
        logistics = next(group for group in result["breakdown_groups"] if group["key"] == "物流")
        self.assertEqual(logistics["amount"], "3.00")
        self.assertEqual([row["key"] for row in logistics["items"]], ["seller_shipping_cost", "buyer_shipping_fee"])
        self.assertEqual(result["revenue"], "79.90")

    def test_customer_refund_reduces_transaction_fee_base_without_reducing_revenue(self):
        result = calculate_profit(self.base_payload(customer_refund=Decimal("10.00")))
        transaction = next(row for row in result["breakdown"] if row["key"] == "transaction_fee")
        self.assertEqual(result["revenue"], "79.90")
        self.assertEqual(result["customer_refund"], "10.00")
        self.assertEqual(transaction["amount"], "2.64")

    def test_east_malaysia_buyer_shipping_is_charged_once_for_multiple_skus(self):
        payload = self.base_payload(buyer_pays_shipping=True, buyer_shipping_region="east_malaysia")
        payload["items"].append(dict(payload["items"][0], sku_name="第二件"))
        result = calculate_profit(payload)
        self.assertEqual(result["shipping"]["buyer_shipping_amount"], "8.00")
        self.assertEqual(result["transaction_fee"]["base"], "167.80")
        self.assertEqual([item["buyer_shipping_fee"] for item in result["items"]], ["8.00", "0.00"])
        logistics = next(group for group in result["breakdown_groups"] if group["key"] == "物流")
        self.assertEqual(logistics["amount"], "6.00")

    def test_transaction_fee_adjustment_is_percentage_points_and_never_negative(self):
        result = calculate_profit(self.base_payload(transaction_fee_adjustment=Decimal("1.22")))
        self.assertEqual(result["transaction_fee"]["official_rate"], "3.78")
        self.assertEqual(result["transaction_fee"]["applied_rate"], "5.00")
        self.assertEqual(result["transaction_fee"]["amount"], "4.00")
        zero = calculate_profit(self.base_payload(transaction_fee_adjustment=Decimal("-9")))
        self.assertEqual(zero["transaction_fee"]["applied_rate"], "0.00")
        self.assertEqual(zero["transaction_fee"]["amount"], "0.00")

    def test_unrelated_actual_settlement_values_never_override_estimate(self):
        expected = calculate_profit(self.base_payload())
        payload = self.base_payload()
        payload.update({
            "actual_platform_commission": Decimal("0"),
            "actual_transaction_fee": Decimal("0"),
            "actual_bxp_fee": Decimal("0"),
            "actual_affiliate_commission": Decimal("0"),
            "actual_seller_shipping_cost": Decimal("0"),
            "actual_platform_support_fee": Decimal("0"),
        })
        self.assertEqual(calculate_profit(payload), expected)

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
        self.organization = Organization.objects.create(name="东铂", slug="profit-calculator")
        Membership.objects.create(organization=self.organization, user=self.user, role=Membership.Role.ADMIN)
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
        self.assertEqual(response.data["shipping_source_file"], "东南亚跨境物流运费价格表20260515(1).xlsx")
        self.assertEqual(response.data["shipping_max_weight_g"], "30000")
        self.assertGreater(len(response.data["categories"]), 240)
        self.assertEqual(
            [node["label"] for node in response.data["category_tree"]],
            ["箱包", "美妆个护"],
        )
        self.assertEqual(len(response.data["categories"][0]["path"]), 3)
        self.assertTrue(response.data["sources"]["lvg_tax"].startswith("https://mysst.customs.gov.my/"))

    def test_strategy_create_and_update_atomically_promote_the_default(self):
        config = {
            "country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace", "bxp": False,
            "commission_adjustment": "1.00", "buyer_pays_shipping": True, "buyer_shipping_region": "west_malaysia",
            "transaction_fee_adjustment": "0.00", "display_currency": "MYR",
        }
        first = self.client.post("/api/profit-calculator/strategies/", {"name": "默认西马", "config": config}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post("/api/profit-calculator/strategies/", {"name": "东马策略", "config": {**config, "buyer_shipping_region": "east_malaysia"}}, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(ProfitCalculationStrategy.objects.filter(organization=self.organization, is_default=True).count(), 1)
        self.assertEqual(ProfitCalculationStrategy.objects.get(is_default=True).name, "东马策略")
        update = self.client.patch("/api/profit-calculator/strategies/%s/" % first.data["id"], {"name": "西马已覆盖", "config": config}, format="json")
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(ProfitCalculationStrategy.objects.get(is_default=True).name, "西马已覆盖")
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action="profit_strategy.update").exists())

    def test_same_name_create_overwrites_inside_a_transaction_and_becomes_default(self):
        config = {"country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace", "bxp": False, "commission_adjustment": "1", "buyer_pays_shipping": False, "buyer_shipping_region": "west_malaysia", "transaction_fee_adjustment": "0", "display_currency": "MYR"}
        first = self.client.post("/api/profit-calculator/strategies/", {"name": "唯一名称", "config": config}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post("/api/profit-calculator/strategies/", {"name": "唯一名称", "config": {**config, "transaction_fee_adjustment": "2.00"}}, format="json")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(ProfitCalculationStrategy.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(second.data["config"]["transaction_fee_adjustment"], "2.00")
        self.assertTrue(second.data["is_default"])
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action="profit_strategy.overwrite").exists())

    def test_strategy_activate_and_delete_keep_one_default_then_allow_empty_list(self):
        config = {"country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace", "bxp": False, "commission_adjustment": "1", "buyer_pays_shipping": True, "buyer_shipping_region": "west_malaysia", "transaction_fee_adjustment": "0", "display_currency": "MYR"}
        first = self.client.post("/api/profit-calculator/strategies/", {"name": "A 西马", "config": config}, format="json")
        second = self.client.post("/api/profit-calculator/strategies/", {"name": "B 东马", "config": {**config, "buyer_shipping_region": "east_malaysia"}}, format="json")
        activated = self.client.post("/api/profit-calculator/strategies/%s/activate/" % first.data["id"], format="json")
        self.assertEqual(activated.status_code, 200, activated.data)
        self.assertEqual(ProfitCalculationStrategy.objects.filter(organization=self.organization, is_default=True).count(), 1)
        self.assertEqual(str(ProfitCalculationStrategy.objects.get(organization=self.organization, is_default=True).pk), str(first.data["id"]))
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action="profit_strategy.activate").exists())
        deleted = self.client.delete("/api/profit-calculator/strategies/%s/" % first.data["id"])
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(str(ProfitCalculationStrategy.objects.get(organization=self.organization, is_default=True).pk), str(second.data["id"]))
        self.assertEqual(self.client.delete("/api/profit-calculator/strategies/%s/" % second.data["id"]).status_code, 204)
        self.assertFalse(ProfitCalculationStrategy.objects.filter(organization=self.organization).exists())
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action="profit_strategy.delete").exists())

    def test_strategy_writes_are_organization_scoped_and_disabled_shipping_uses_west_malaysia(self):
        config = {"country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace", "bxp": False, "commission_adjustment": "1", "buyer_pays_shipping": False, "buyer_shipping_region": "east_malaysia", "transaction_fee_adjustment": "0", "display_currency": "MYR"}
        created = self.client.post("/api/profit-calculator/strategies/", {"name": "本组织策略", "config": config}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["config"]["buyer_shipping_region"], "west_malaysia")
        other_user = get_user_model().objects.create_user(username="other-calculator", password="test-pass-123")
        other_organization = Organization.objects.create(name="其他组织", slug="other-profit-calculator")
        Membership.objects.create(organization=other_organization, user=other_user, role=Membership.Role.ADMIN, permissions=["profit_rules"])
        other_client = APIClient()
        other_client.force_authenticate(other_user)
        path = "/api/profit-calculator/strategies/%s/" % created.data["id"]
        # The role permission guard may reject before lookup (403); either way a
        # different organization cannot read or mutate this strategy.
        self.assertEqual(other_client.get(path).status_code, 403)
        self.assertEqual(other_client.post(path + "activate/", format="json").status_code, 403)
        self.assertEqual(other_client.patch(path, {"name": "越权", "config": config}, format="json").status_code, 403)
        self.assertEqual(other_client.delete(path).status_code, 403)

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

    def test_calculate_rejects_weight_outside_shipping_price_list(self):
        response = self.client.post("/api/profit-calculator/calculate/", {
            "country": "MY",
            "seller_type": "cross_border",
            "shop_identity": "marketplace",
            "cny_per_myr": "1.68",
            "items": [{
                "category_code": "bag-womens-womens-tote-bags",
                "weight_g": "30001",
                "item_price": "10.00",
            }],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("超过当前运费价表范围", str(response.data["items"][0]["weight_g"]))

    @patch("apps.erp.exchange_rates.urlopen", return_value=FakeRateResponse())
    def test_exchange_rates_are_derived_from_one_ecb_daily_snapshot(self, mocked_urlopen):
        response = self.client.get("/api/profit-calculator/exchange-rates/?refresh=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["date"], "2026-07-29")
        self.assertEqual(response.data["cny_per_myr"], "1.680000")
        self.assertEqual(response.data["usd_per_myr"], "0.232000")
        self.assertEqual(response.data["source"], "European Central Bank")
        self.assertFalse(response.data["stale"])
        mocked_urlopen.assert_called_once()

    @patch("apps.erp.exchange_rates.urlopen", side_effect=TimeoutError("upstream timeout"))
    def test_exchange_rates_return_last_good_snapshot_when_refresh_fails(self, mocked_urlopen):
        ExchangeRateSnapshot.objects.create(
            organization=self.organization, effective_date="2026-07-28",
            fetched_at=timezone.now(), myr_cny="1.67000000", myr_usd="0.23100000", source="Manual",
            source_url="", validation_status="valid", is_current=True,
        )
        response = self.client.get("/api/profit-calculator/exchange-rates/?refresh=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["date"], "2026-07-28")
        self.assertTrue(response.data["stale"])
        self.assertGreaterEqual(mocked_urlopen.call_count, 3)

    @patch("apps.erp.exchange_rates.urlopen", side_effect=[
        TimeoutError("primary timeout"), TimeoutError("primary timeout"),
        FakePayloadResponse(b'{"date":"2026-08-03","rates":{"CNY":1.690000,"USD":0.236000}}'),
    ])
    def test_exchange_rates_switch_to_backup_source_and_persist_failure_summary(self, mocked_urlopen):
        ExchangeRateSnapshot.objects.create(
            organization=self.organization, effective_date="2026-08-02", fetched_at=timezone.now(),
            myr_cny="1.680000", myr_usd="0.235000", source="European Central Bank",
            source_url="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            validation_status="valid", is_current=True,
        )
        response = self.client.get("/api/profit-calculator/exchange-rates/?refresh=1")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["source"], "Frankfurter")
        self.assertEqual(len(response.data["failures"]), 2)
        snapshot = ExchangeRateSnapshot.objects.get(pk=response.data["id"])
        self.assertEqual(snapshot.myr_cny, Decimal("1.690000"))
        self.assertEqual(snapshot.myr_usd, Decimal("0.236000"))
        self.assertIn("earlier failures", snapshot.response_summary)
        self.assertEqual(mocked_urlopen.call_count, 3)
        self.assertTrue(AuditLog.objects.filter(
            organization=self.organization, object_id=str(snapshot.pk), action="exchange_rate.source_switch"
        ).exists())

    @patch("apps.erp.exchange_rates.urlopen")
    def test_background_refresh_preserves_manual_current_snapshot(self, mocked_urlopen):
        manual = ExchangeRateSnapshot.objects.create(
            organization=self.organization, effective_date=timezone.localdate(), fetched_at=timezone.now(),
            myr_cny="1.700000", myr_usd="0.240000", source="Manual",
            validation_status="manual", is_current=True,
        )
        snapshot, failures = refresh_snapshot(self.organization, respect_manual=True)
        self.assertEqual(snapshot.pk, manual.pk)
        self.assertEqual(failures, ["manual override preserved"])
        mocked_urlopen.assert_not_called()
