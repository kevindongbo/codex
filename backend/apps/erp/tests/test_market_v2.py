from copy import deepcopy
from decimal import Decimal
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.erp.models import MarketSnapshot, Membership, Organization, OwnStore, Product, SKU, StoreProduct
from apps.erp.market_calculator import allocation, package_metrics, PackageInput


@override_settings(MARKET_MX_ENABLED=True)
class MarketV2Tests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="团队", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.owner = get_user_model().objects.create_user(username="owner", is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.base = "/api/profit-calculator/v2/"

    def post(self, path, data, status=200, **headers):
        r = self.client.post(self.base + path, data, format="json", **headers)
        self.assertEqual(r.status_code, status, r.data)
        return r.data

    def item(self, c="US", name="camera-1", price="100", quantity=1):
        return {"client_item_id": name, "sku_name": name, "category_mapping_id": c + ":home_security", "quantity": quantity,
            "unit_price": price, "product_cost_cny": "140", "first_leg_cost_cny": "21", "affiliate_rate": "10",
            "commission_rate": "6", "commission_source": "商家确认类目佣金", "other_cost": "0", "other_cost_source": "已包含，无其他成本",
            "tax_expense": "0", "tax_withholding": "0", "tax_source": "测试税务依据", "ad_mode": "none"}

    def package(self, item="camera-1", quantity=1):
        return {"client_package_id": "parcel-1", "items": [{"client_item_id": item, "quantity": quantity}],
                "weight": {"value": "2", "unit": "lb"}, "dimensions": {"length": "10", "width": "8", "height": "3", "unit": "in"},
                "battery_profile": "plug_in_no_battery"}

    def data(self, c="US", quantity=1):
        return {"schema_version": 2, "country": c, "currency": "USD" if c == "US" else "MXN", "seller_program": "local",
                "fulfillment_service": "seller_shipping", "items": [self.item(c, price="100" if c == "US" else "1000", quantity=quantity)],
                "packages": [self.package(quantity=quantity)], "fees_confirmed": True, "mx_fee_units_confirmed": True}

    def rate(self, c="US", cny="7", usd="1"):
        return self.post("exchange-rates/", {"country": c, "cny_per_base": cny, "usd_per_base": usd, "source": "测试人工汇率"}, 201)

    def quote(self, data, price="8", channel="offline", expected=201):
        return self.post("shipping-quotes/", {k: v for k, v in data.items() if k in ["country", "currency", "store_id", "seller_program", "fulfillment_service", "packages"]} | {
            "lines": [{"package_id": p["client_package_id"], "amount": price} for p in data["packages"]], "source": "仓库确认报价，含附加费",
            "origin": "当地仓", "destination": "90210", "payment_channel": channel, "includes": ["last_mile", "surcharges"],
            "eligibility_confirmed": True, "battery_accepted": True, "surcharges_confirmed": True}, expected)

    def complete(self, data=None, price="8", channel="offline"):
        data = data or self.data()
        c = data["country"]
        data["exchange_rate_set_id"] = self.rate(c, "7" if c == "US" else ".35", "1" if c == "US" else ".05")["id"]
        data["shipping_quote_id"] = self.quote(data, price, channel)["id"]
        return data

    def test_us_golden_profit_payout_ads_and_fee_base(self):
        data = self.complete()
        result = self.post("calculate/", data)
        self.assertEqual(result["mode"], "merchant_scenario")
        self.assertEqual((result["gross_profit"], result["break_even_roi"], result["platform_payout"], result["net_profit"]), ("53.00", "1.89", "84.00", None))
        data["items"][0].update(ad_mode="cpa_usd", ad_value="10")
        result = self.post("calculate/", data)
        self.assertEqual(result["net_profit"], "43.00")
        data["shipping_quote_id"] = self.quote(data, channel="platform")["id"]
        result = self.post("calculate/", data)
        self.assertEqual((result["gross_profit"], result["platform_payout"]), ("53.00", "76.00"))
        data.update(buyer_shipping="10", checkout_sales_tax="8")
        data["items"][0]["platform_discount"] = "5"
        result = self.post("calculate/", data)
        self.assertEqual(result["items"][0]["fee_base"], "110.00")
        self.assertEqual(result["items"][0]["fees"][4]["amount"], "6.60")

    def test_mx_sfp_per_item_and_zero_commission_does_not_waive_fixed(self):
        data = self.complete(self.data("MX"), price="0")
        data.update(sfp=True, sfp_confirmed=True)
        r = self.post("calculate/", data)
        fee = {f["label"]: f["amount"] for f in r["items"][0]["fees"]}
        self.assertEqual((fee["平台佣金"], fee["售出固定费"], fee["SFP服务费"]), ("60.00", "6.00", "40.00"))
        data["items"][0]["unit_price"] = "300"
        r = self.post("calculate/", data)
        self.assertEqual(r["items"][0]["fees"][6]["amount"], "24.00")
        data["items"][0]["commission_rate"] = "0"
        r = self.post("calculate/", data)
        self.assertEqual(r["items"][0]["fees"][4]["amount"], "0.00")
        self.assertEqual(r["items"][0]["fees"][5]["amount"], "6.00")
        data["mx_fee_units_confirmed"] = False
        r = self.post("calculate/", data)
        self.assertEqual((r["calculation_status"], r["gross_profit"], r["break_even_roi"]), ("partial", None, None))

    def test_missing_is_not_zero_and_negative_margin_has_no_roi(self):
        data = self.complete()
        del data["items"][0]["first_leg_cost_cny"]
        r = self.post("calculate/", data)
        self.assertIsNone(r["gross_profit"])
        data["items"][0]["first_leg_cost_cny"] = "0"
        data["items"][0]["product_cost_cny"] = "7000"
        r = self.post("calculate/", data)
        self.assertLess(Decimal(r["gross_profit"]), 0)
        self.assertIsNone(r["break_even_roi"])
        self.assertIsNone(r["net_profit"])

    def test_quote_binding_battery_country_units_and_packages(self):
        data = self.complete()
        data["packages"][0]["weight"]["value"] = "3"
        self.post("calculate/", data, 409)
        data["packages"][0]["weight"]["value"] = "2"
        wrong = deepcopy(data)
        wrong["items"][0]["category_mapping_id"] = "MX:home_security"
        self.post("calculate/", wrong, 400)
        wrong = deepcopy(data)
        wrong["currency"] = "MYR"
        self.post("calculate/", wrong, 400)
        wrong = deepcopy(data)
        wrong["packages"][0]["items"][0]["quantity"] = 2
        self.post("calculate/", wrong, 400)
        wrong = deepcopy(data)
        wrong["packages"][0]["battery_profile"] = "unknown"
        self.quote(wrong, expected=400)
        mx = self.data("MX")
        mx["fulfillment_service"] = "platform_warehouse"
        self.quote(mx, expected=400)
        mx["fulfillment_service"] = "platform_label_standard"
        mx["packages"][0]["weight"] = {"value": "30.000001", "unit": "kg"}
        self.quote(mx, expected=400)
        p = PackageInput(data=self.package())
        self.assertTrue(p.is_valid(), p.errors)
        self.assertEqual(Decimal(package_metrics(p.validated_data)["actual_weight_g"]), Decimal("907.18474"))

    def test_mixed_package_cost_allocations_sum_and_tax_cashflow(self):
        data = self.data()
        data["items"] = [self.item(name="a", price="30"), self.item(name="b", price="70")]
        data["packages"][0]["items"] = [{"client_item_id": "a", "quantity": 1}, {"client_item_id": "b", "quantity": 1}]
        data = self.complete(data, price="10")
        r = self.post("calculate/", data)
        self.assertEqual([i["fees"][3]["amount"] for i in r["items"]], ["3.00", "7.00"])
        self.assertEqual(allocation(Decimal(".01"), [Decimal(1), Decimal(1)]), [Decimal(".01"), Decimal(".00")])
        old_g, old_p = Decimal(r["gross_profit"]), Decimal(r["platform_payout"])
        data["items"][0]["tax_withholding"] = "2"
        r = self.post("calculate/", data)
        self.assertEqual(Decimal(r["gross_profit"]), old_g)
        self.assertEqual(Decimal(r["platform_payout"]), old_p - 2)

    def test_save_recalculates_context_idempotency_and_immutable_history(self):
        data = self.complete()
        r = self.post("calculate/", data)
        body = {"input": data, "name": "camera plan", "expected_context_hash": r["context_hash"]}
        key = str(uuid.uuid4())
        saved = self.post("plans/save/", body, 201, HTTP_IDEMPOTENCY_KEY=key)
        again = self.post("plans/save/", body, HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(saved["id"], again["id"])
        self.post("plans/save/", {**body, "name": "other"}, 409, HTTP_IDEMPOTENCY_KEY=key)
        record = MarketSnapshot.objects.get(pk=saved["id"])
        with self.assertRaises(ModelValidationError):
            record.save()
        self.rate()  # Current organization rate context changed.
        self.post("plans/save/", body, 409, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        old = self.client.get(self.base + f"plans/{record.pk}/?country=US")
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.data["payload"]["result"]["gross_profit"], "53.00")

    def test_workspaces_and_strategy_names_are_country_isolated(self):
        for c in ("US", "MX"):
            r = self.client.put(self.base + "working-config/?country=" + c, {"revision": 0, "config": {"country": c}}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["revision"], 1)
            self.post("strategies/?country=" + c, {"name": "默认策略", "config": {"country": c}, "is_default": True})
        response = self.client.put(self.base + "working-config/?country=US", {"revision": 0, "config": {}}, format="json")
        self.assertEqual(response.status_code, 409)
        wrong = self.client.put(self.base + "working-config/?country=US", {"revision": 1, "config": {"country": "MX"}}, format="json")
        self.assertEqual(wrong.status_code, 400)

    def test_market_prices_roundtrip_and_legacy_myr_rejected_in_us(self):
        product = Product.objects.create(organization=self.org, name="摄像头")
        sku = SKU.objects.create(organization=self.org, product=product, code="CAM-01")
        store_ids = []
        for c, cur in [("MY", "MYR"), ("US", "USD"), ("MX", "MXN")]:
            r = self.client.post("/api/stores/", {"name": c + "店", "market": c}, format="json")
            self.assertEqual(r.status_code, 201, r.data)
            store_ids.append(r.data["id"])
            listing = self.client.post("/api/store-products/", {"store": r.data["id"], "sku": str(sku.pk), "price_amount": "100.00", "currency": cur, "commission_override_percent": "0"}, format="json")
            self.assertEqual(listing.status_code, 201, listing.data)
            self.assertEqual(listing.data["currency"], cur)
            self.assertEqual(listing.data["commission_override_percent"], "0.00")
        us_listing = StoreProduct.objects.get(store_id=store_ids[1])
        self.assertIsNone(us_listing.sale_price_myr)
        r = self.client.patch(f"/api/store-products/{us_listing.pk}/", {"sale_price_myr": "200"}, format="json")
        self.assertEqual(r.status_code, 400)
        summary = self.client.get("/api/skus/profit-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertIsNone(summary.data[0]["sale_price"])

    @override_settings(MARKET_V2_ENABLED=False)
    def test_feature_switch(self):
        self.assertEqual(self.client.get(self.base + "config/?country=US").status_code, 404)

    def test_linked_sku_profile_plan_and_store_summary_never_inherit_my_commission(self):
        product = Product.objects.create(organization=self.org, name="安防摄像头")
        sku = SKU.objects.create(organization=self.org, product=product, code="CAM-US", cost="140", currency="CNY", purchase_cost_cny="140", default_creator_commission_percent="99")
        store = OwnStore.objects.create(organization=self.org, name="US店", country_code="US", currency="USD", seller_program="local", fulfillment_capabilities=["seller_shipping"])
        listing = StoreProduct.objects.create(organization=self.org, sku=sku, store=store, country="US", currency="USD", price_amount="100", commission_override_percent=None)
        profile = self.client.put(self.base + f"sku-profiles/{sku.pk}/?country=US", {"revision": 0, "category_mapping_id": "US:home_security", "weight": {"value": "500", "unit": "g"},
            "dimensions": {"length": "20", "width": "15", "height": "10", "unit": "cm"}, "battery_profile": "plug_in_no_battery", "affiliate_rate": "10"}, format="json")
        self.assertEqual(profile.status_code, 200, profile.data)
        data = self.data()
        data["store_id"] = str(store.pk)
        data["items"][0]["sku_id"] = str(sku.pk)
        data = self.complete(data)
        result = self.post("calculate/", data)
        self.post("plans/save/", {"input": data, "expected_context_hash": result["context_hash"], "name": "US linked"}, 201, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        summary = self.client.get("/api/skus/profit-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        detail = summary.data[0]["stores"][0]
        self.assertEqual((detail["calculable"], detail["gross_profit"], detail["currency"]), (True, "53.00", "USD"))
        listing.price_amount = "101"
        listing.save()
        summary = self.client.get("/api/skus/profit-summary/")
        self.assertFalse(summary.data[0]["stores"][0]["calculable"])

    def test_manual_rates_permission_and_cross_organization_quote(self):
        other = Organization.objects.create(name="其他", slug="other")
        fake = MarketSnapshot.objects.create(organization=other, kind="quote", country="US", currency="USD", payload={}, content_hash="other")
        data = self.data()
        data["shipping_quote_id"] = str(fake.pk)
        self.post("calculate/", data, 404)
        user = get_user_model().objects.create_user(username="rules-only")
        Membership.objects.create(organization=self.org, user=user, role="viewer", permissions=["profit_rules"])
        self.client.force_authenticate(user)
        self.post("exchange-rates/", {"country": "US", "cny_per_base": "7", "usd_per_base": "1", "source": "manual"}, 403)
        self.assertEqual(self.client.get(self.base + "config/?country=US").status_code, 200)
