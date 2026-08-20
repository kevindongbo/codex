from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.erp.models import (
    AuditLog,
    CreatorAttribution,
    CreatorCollaboration,
    CreatorContent,
    CreatorFollowUp,
    CreatorProfile,
    CreatorSample,
    ExchangeRateSnapshot,
    Membership,
    Organization,
    Product,
    ProfitCalculationBatch,
    ProfitPlan,
    ProfitPlanVersion,
    SKU,
    Warehouse,
)


class NewWorkflowApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="workflow-admin", password="test-pass-123")
        self.organization = Organization.objects.create(name="东铂", slug="workflow-api")
        Membership.objects.create(organization=self.organization, user=self.user, role=Membership.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        self.warehouse = Warehouse.objects.create(organization=self.organization, code="MY-01", name="马来仓")
        self.product = Product.objects.create(organization=self.organization, name="豹纹托特", status=Product.Status.ACTIVE)
        self.sku = SKU.objects.create(
            organization=self.organization, product=self.product, code="AI-BAG-BROWN-05",
            cost="18.90", category_code="bag-womens-womens-tote-bags", packed_weight_g="200",
        )

    def test_creator_nickname_only_and_every_child_workflow(self):
        created = self.client.post("/api/creators/", {"display_name": "阿琳"}, format="json", **self.headers)
        self.assertEqual(created.status_code, 201, created.data)
        creator_id = created.data["id"]
        self.assertTrue(created.data["incomplete"])

        collaboration = self.client.post(
            f"/api/creators/{creator_id}/collaborations/",
            {"stage": "contacted", "sku": str(self.sku.pk), "commission_percent": "12.50"},
            format="json", **self.headers,
        )
        self.assertEqual(collaboration.status_code, 201, collaboration.data)
        collaboration_id = collaboration.data["id"]
        child_payloads = [
            ("samples", {"collaboration": collaboration_id, "sku": str(self.sku.pk), "quantity": "2", "tracking_number": "", "status": "pending"}),
            ("contents", {"collaboration": collaboration_id, "content_type": "video", "url": "", "notes": "待发布"}),
            ("followups", {"collaboration": collaboration_id, "note": "下周再次联系"}),
            ("attributions", {"collaboration": collaboration_id, "source": "unattributed", "order_count": 0, "units": "0"}),
        ]
        for path, payload in child_payloads:
            response = self.client.post(f"/api/creators/{creator_id}/{path}/", payload, format="json", **self.headers)
            self.assertEqual(response.status_code, 201, (path, response.data))
        self.assertEqual(CreatorProfile.objects.count(), 1)
        self.assertEqual(CreatorCollaboration.objects.count(), 1)
        self.assertEqual(CreatorSample.objects.count(), 1)
        self.assertEqual(CreatorContent.objects.count(), 1)
        self.assertEqual(CreatorFollowUp.objects.count(), 1)
        self.assertEqual(CreatorAttribution.objects.get().source, "unattributed")
        audit_text = str(list(AuditLog.objects.filter(action__startswith="creator.").values_list("after", flat=True)))
        self.assertNotIn("下周再次联系", audit_text)

    def test_analytics_exact_sku_filter(self):
        other_product = Product.objects.create(organization=self.organization, name="另一商品")
        SKU.objects.create(organization=self.organization, product=other_product, code="OTHER-SKU")
        response = self.client.get(f"/api/analytics/skus/?sku={self.sku.pk}&days=7", **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["sku"] for row in response.data["results"]], [str(self.sku.pk)])

    def test_profit_plan_prepare_then_explicit_new_version_and_idempotency(self):
        ExchangeRateSnapshot.objects.create(
            organization=self.organization, effective_date=timezone.localdate(), fetched_at=timezone.now(),
            myr_cny="1.680000", myr_usd="0.235000", source="Manual", validation_status="manual", is_current=True,
        )
        base = {
            "country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace",
            "cny_per_myr": "1.68", "usd_per_myr": "0.235",
            "advertising_rebate_percent": "10", "items": [{
                "sku": str(self.sku.pk), "sku_name": self.sku.code,
                "category_code": "bag-womens-womens-tote-bags", "weight_g": "200",
                "product_cost_cny": "18.90", "item_price": "79.90", "affiliate_rate": "15.00",
                "ad_cost_type": "roi", "ad_cost_value": "4", "action": "new_plan",
            }],
        }
        first_payload = {**base, "idempotency_key": "profit-batch-001"}
        first = self.client.post("/api/profit-calculator/plans/", first_payload, format="json", **self.headers)
        self.assertEqual(first.status_code, 201, first.data)
        repeated = self.client.post("/api/profit-calculator/plans/", first_payload, format="json", **self.headers)
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(first.data, repeated.data)
        self.assertEqual(ProfitCalculationBatch.objects.count(), 1)
        plan_id = first.data["plans"][0]["plan_id"]
        version_id = first.data["plans"][0]["version_id"]

        prepared = self.client.post(
            f"/api/profit-calculator/plans/{plan_id}/recalculate/", {"version": version_id},
            format="json", **self.headers,
        )
        self.assertEqual(prepared.status_code, 200, prepared.data)
        self.assertEqual(prepared.data["target_plan"], plan_id)
        self.assertEqual(ProfitPlanVersion.objects.filter(plan_id=plan_id).count(), 1)

        recalculation = dict(prepared.data["calculation"])
        recalculation["items"][0].update({"action": "new_version", "target_plan": plan_id, "item_price": "89.90"})
        recalculation["idempotency_key"] = "profit-batch-002"
        saved = self.client.post("/api/profit-calculator/plans/", recalculation, format="json", **self.headers)
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["plans"][0]["version_number"], 2)
        self.assertEqual(ProfitPlan.objects.count(), 1)
        self.assertEqual(ProfitPlanVersion.objects.filter(plan_id=plan_id).count(), 2)
