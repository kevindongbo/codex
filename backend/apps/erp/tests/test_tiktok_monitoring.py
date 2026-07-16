from decimal import Decimal
from io import StringIO
import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.erp.models import AuditLog, CompetitorProduct, CompetitorSnapshot, Membership, Organization
from apps.erp.services import collect_tiktok_competitor_snapshot
from apps.erp.tiktok_monitoring import (
    ApifyProvider,
    MonitoringDataError,
    MonitoringProviderError,
    TikHubProvider,
    TikTokProductObservation,
    extract_tiktok_product_id,
    fetch_tiktok_observation,
)


class TikTokProviderTests(SimpleTestCase):
    def test_extracts_my_product_ids_from_supported_public_urls(self):
        product_id = "1734050283349837382"
        self.assertEqual(extract_tiktok_product_id(product_id), product_id)
        self.assertEqual(
            extract_tiktok_product_id(f"https://www.tiktok.com/view/product/{product_id}"),
            product_id,
        )
        self.assertEqual(
            extract_tiktok_product_id(f"https://shop.tiktok.com/my/pdp/bag/{product_id}?foo=1"),
            product_id,
        )
        self.assertEqual(
            extract_tiktok_product_id(f"https://www.tiktok.com/shop/pdp/bag?product_id={product_id}"),
            product_id,
        )
        with self.assertRaises(MonitoringDataError):
            extract_tiktok_product_id("https://vt.tiktok.com/short-code/")
        with self.assertRaises(MonitoringDataError):
            extract_tiktok_product_id(f"https://example.com/product/{product_id}")

    def test_tikhub_uses_my_region_and_parses_public_product_facts(self):
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append((method, url, headers, body, timeout))
            return {
                "code": 200,
                "data": {
                    "productInfo": {
                        "productId": "1734050283349837382",
                        "title": "Butterfly tote bag",
                        "price": {"salePrice": {"priceVal": "18.69", "currency": "MYR"}},
                        "soldInfo": {"soldCount": "1.2K sold"},
                        "reviewInfo": {"rating": "4.8", "reviewCount": 321},
                        "shopInfo": {"shopName": "Tas Inspirasi"},
                        "images": [{"url": "https://example.com/bag.jpg"}],
                        "isInStock": True,
                    }
                },
            }

        observation = TikHubProvider(token="secret", transport=transport).fetch(
            product_id="1734050283349837382",
            market="MY",
            product_url="https://www.tiktok.com/view/product/1734050283349837382",
        )

        self.assertEqual(observation.provider, "tikhub")
        self.assertEqual(observation.price, Decimal("18.69"))
        self.assertEqual(observation.currency, "MYR")
        self.assertEqual(observation.sold_count, 1200)
        self.assertEqual(observation.rating, Decimal("4.8"))
        self.assertEqual(observation.review_count, 321)
        self.assertEqual(observation.seller, "Tas Inspirasi")
        self.assertEqual(observation.availability, "in_stock")
        self.assertIn("region=MY", calls[0][1])
        self.assertNotIn("secret", calls[0][1])
        self.assertEqual(calls[0][2]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0][4], 30)

    def test_apify_caps_charge_and_pins_residential_proxy_to_my(self):
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append((method, url, headers, json.loads(body), timeout))
            return [{
                "product_id": "1734050283349837382",
                "title": "Fallback bag",
                "price": 19.2,
                "currency": "MYR",
                "sold_count": 902,
                "rating": 4.7,
                "review_count": 88,
                "shop_name": "Fallback shop",
                "image_urls": ["https://example.com/fallback.jpg"],
                "stock_count": 5,
            }]

        observation = ApifyProvider(
            token="apify-secret",
            transport=transport,
            timeout=120,
            max_charge_usd="0.10",
        ).fetch(
            product_id="1734050283349837382",
            market="MY",
            product_url="https://www.tiktok.com/view/product/1734050283349837382",
        )

        self.assertEqual(observation.provider, "apify")
        self.assertEqual(observation.sold_count, 902)
        self.assertIn("maxTotalChargeUsd=0.10", calls[0][1])
        self.assertNotIn("apify-secret", calls[0][1])
        self.assertEqual(calls[0][3]["productIds"], ["1734050283349837382"])
        self.assertEqual(calls[0][3]["proxyConfiguration"]["countryCode"], "MY")
        self.assertEqual(calls[0][3]["proxyConfiguration"]["apifyProxyGroups"], ["RESIDENTIAL"])

    def test_provider_chain_falls_back_and_records_the_failed_primary(self):
        class Primary:
            name = "primary"

            def fetch(self, **kwargs):
                raise MonitoringProviderError("temporary upstream failure")

        class Fallback:
            name = "fallback"

            def fetch(self, **kwargs):
                return TikTokProductObservation(
                    provider="fallback",
                    product_id=kwargs["product_id"],
                    market="MY",
                    captured_at=timezone.now(),
                    canonical_url=kwargs["product_url"],
                    sold_count=10,
                )

        observation = fetch_tiktok_observation(
            "https://www.tiktok.com/view/product/1734050283349837382",
            providers=[Primary(), Fallback()],
        )
        self.assertEqual(observation.provider, "fallback")
        self.assertEqual(observation.attempts[0]["provider"], "primary")
        self.assertIn("temporary upstream failure", observation.attempts[0]["error"])


class TikTokMonitoringDatabaseTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="东铂", slug=settings.INTERNAL_ORGANIZATION_SLUG
        )
        self.product = CompetitorProduct.objects.create(
            organization=self.organization,
            name="",
            kind=CompetitorProduct.Kind.DIRECT,
            platform="other",
            market="MY",
            url="https://www.tiktok.com/view/product/1734050283349837382",
            currency="CNY",
        )

    @staticmethod
    def provider(*, sold, price=None, rating=None, reviews=None):
        class FakeProvider:
            name = "fake"

            def fetch(self, **kwargs):
                return TikTokProductObservation(
                    provider="fake",
                    product_id=kwargs["product_id"],
                    market="MY",
                    captured_at=timezone.now(),
                    canonical_url=kwargs["product_url"],
                    title="自动识别商品",
                    seller="MY Seller",
                    currency="MYR",
                    price=price,
                    sold_count=sold,
                    rating=rating,
                    review_count=reviews,
                    availability="in_stock",
                    image_url="https://example.com/product.jpg",
                    metadata={"rating_distribution": {"1": 2, "2": 3, "5": 20}},
                )

        return FakeProvider()

    def test_service_creates_baseline_enriches_profile_and_flags_sales_decrease(self):
        baseline = collect_tiktok_competitor_snapshot(
            product=self.product,
            providers=[self.provider(sold=901, price=Decimal("18.69"), rating=Decimal("4.8"), reviews=25)],
        )
        self.product.refresh_from_db()
        self.assertEqual(baseline.sold_count, 901)
        self.assertEqual(baseline.raw["low_reviews"], 5)
        self.assertEqual(baseline.raw["monitoring"]["provider"], "fake")
        self.assertTrue(baseline.raw["monitoring"]["public_data"])
        self.assertEqual(self.product.name, "自动识别商品")
        self.assertEqual(self.product.seller, "MY Seller")
        self.assertEqual(self.product.currency, "MYR")
        self.assertEqual(self.product.platform, "tiktok_shop")

        decreased = collect_tiktok_competitor_snapshot(
            product=self.product,
            providers=[self.provider(sold=899)],
        )
        self.assertEqual(decreased.price, baseline.price)
        self.assertEqual(decreased.rating, baseline.rating)
        self.assertIn("price", decreased.raw["monitoring"]["inherited_fields"])
        self.assertEqual(decreased.raw["monitoring"]["anomaly"], "cumulative_sold_decreased")
        self.assertEqual(
            AuditLog.objects.filter(action="competitor_snapshot.auto_collect").count(), 2
        )

    @override_settings(TIKHUB_API_TOKEN="test-token")
    def test_collect_api_creates_a_snapshot_for_authenticated_catalog_user(self):
        user = get_user_model().objects.create_user(username="monitor-user", password="pass")
        Membership.objects.create(
            organization=self.organization, user=user, role=Membership.Role.ADMIN
        )
        client = APIClient()
        client.force_authenticate(user)
        observation = TikTokProductObservation(
            provider="tikhub",
            product_id="1734050283349837382",
            market="MY",
            captured_at=timezone.now(),
            canonical_url=self.product.url,
            currency="MYR",
            price=Decimal("18.69"),
            sold_count=905,
            rating=Decimal("4.9"),
            review_count=30,
        )
        with patch("apps.erp.tiktok_monitoring.TikHubProvider.fetch", return_value=observation):
            response = client.post(
                f"/api/competitors/{self.product.pk}/collect/",
                {"provider": "auto"},
                format="json",
                HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
            )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["sold_count"], 905)
        self.assertEqual(response.data["raw"]["monitoring"]["provider"], "tikhub")

    @override_settings(TIKHUB_API_TOKEN="test-token")
    def test_management_command_collects_due_my_products(self):
        output = StringIO()

        def fake_collect(*, product, **kwargs):
            return CompetitorSnapshot.objects.create(
                product=product,
                captured_at=timezone.now(),
                sold_count=100,
                raw={"monitoring": {"provider": "tikhub"}},
            )

        with patch(
            "apps.erp.management.commands.monitor_tiktok_products.collect_tiktok_competitor_snapshot",
            side_effect=fake_collect,
        ):
            call_command("monitor_tiktok_products", "--force", stdout=output)
        self.assertIn("成功 1", output.getvalue())
        self.assertEqual(self.product.snapshots.count(), 1)
