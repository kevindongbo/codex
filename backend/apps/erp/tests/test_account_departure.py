import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.erp.models import AccountSecurityState, AuditLog, Membership, Organization, Warehouse
from apps.erp.scheduling_models import ScheduleParticipant


class AccountDepartureTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="团队", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.owner = get_user_model().objects.create_user(username="owner", is_superuser=True)
        self.user = get_user_model().objects.create_user(username="departing", password="Password-long-7721")
        self.member = Membership.objects.create(organization=self.org, user=self.user, role="admin")
        self.warehouse = Warehouse.objects.create(organization=self.org, code="WH", name="仓库")
        self.member.authorized_warehouses.add(self.warehouse)
        ScheduleParticipant.objects.create(organization=self.org, user=self.user, active=True, effective_from=timezone.localdate())
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/internal-accounts/{self.member.pk}/"

    def transition(self, action, data=None, key=None):
        self.member.refresh_from_db()
        return self.client.post(self.url + action + "/", data or {"revision": self.member.revision}, format="json", HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))

    def test_archive_restore_never_revives_access_or_refresh(self):
        login = APIClient().post("/api/auth/token/", {"username": "departing", "password": "Password-long-7721"})
        self.assertEqual(login.status_code, 200, login.data)
        tokens = login.data
        legacy = RefreshToken.for_user(self.user)
        self.assertEqual(self.transition("archive").status_code, 200)
        self.assertEqual(self.client.get("/api/internal-accounts/").data["counts"]["departed"], 1)
        self.assertEqual(self.client.get("/api/purchase-members/").data, [{"user_id": self.owner.pk, "display_name": "owner", "username": "owner", "role": "admin"}])
        self.assertFalse(ScheduleParticipant.objects.get(user=self.user).active)
        self.assertEqual(self.client.patch(self.url, {"active": True}, format="json").status_code, 409)
        restored = self.transition("restore")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.member.refresh_from_db()
        self.assertEqual((self.member.role, self.member.permissions, self.member.active), ("viewer", ["view"], False))
        self.assertEqual(self.member.authorized_warehouses.count(), 0)
        self.assertEqual(self.client.patch(self.url, {"active": True}, format="json").status_code, 409)
        enabled = self.client.patch(self.url, {"password": "New-Password-long-8743", "active": True}, format="json")
        self.assertEqual(enabled.status_code, 200, enabled.data)
        for access in (tokens["access"], str(legacy.access_token)):
            other = APIClient()
            other.credentials(HTTP_AUTHORIZATION="Bearer " + access)
            self.assertEqual(other.get("/api/auth/me/").status_code, 401)
            self.assertEqual(other.post("/api/profit-calculator/calculate/", {}, format="json").status_code, 401)
        for refresh in (tokens["refresh"], str(legacy)):
            self.assertEqual(APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}).status_code, 401)
        self.assertEqual(APIClient().post("/api/auth/token/", {"username": "departing", "password": "New-Password-long-8743"}).status_code, 200)
        self.assertGreater(AccountSecurityState.objects.get(user=self.user).auth_version, 1)

    def test_protection_idempotency_and_stale_revision(self):
        preview = self.client.get(self.url + "departure-preview/")
        self.assertEqual(preview.status_code, 200, preview.data)
        key = str(uuid.uuid4())
        data = {"revision": 1, "reason": "离职", "departure_date": str(timezone.localdate())}
        first = self.transition("archive", data, key)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(self.transition("archive", data, key).data, first.data)
        self.assertEqual(AuditLog.objects.filter(action="account.archive").count(), 1)
        self.assertEqual(self.transition("archive", {**data, "reason": "other"}, key).status_code, 409)
        self.assertEqual(self.transition("restore", {"revision": 1}).status_code, 409)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.transition("restore").status_code, 403)
        self.client.force_authenticate(self.owner)
        owner_member = Membership.objects.get(user=self.owner)
        response = self.client.post(f"/api/internal-accounts/{owner_member.pk}/archive/", {"revision": 1}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 403)

    def test_legacy_disable_and_validation(self):
        future = str(timezone.localdate() + timedelta(days=1))
        self.assertEqual(self.transition("archive", {"revision": 1, "departure_date": future}).status_code, 400)
        self.assertEqual(self.transition("archive", {"revision": 1, "role": "admin"}).status_code, 400)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.member.refresh_from_db()
        self.assertEqual(self.member.employment_status, "employed")
        self.assertFalse(self.member.active)

    def test_historical_purchaser_is_preserved_but_cannot_be_newly_assigned(self):
        from apps.erp.models import Product, SKU, Supplier, PurchaseOrder, PurchaseOrderLine
        product = Product.objects.create(organization=self.org, name="旧商品", status="active")
        sku = SKU.objects.create(organization=self.org, product=product, code="OLD-CAM", cost="10")
        supplier = Supplier.objects.create(organization=self.org, code="S", name="供应商")
        order = PurchaseOrder.objects.create(organization=self.org, number="PO-OLD", supplier=supplier, warehouse=self.warehouse, purchaser=self.user)
        line = PurchaseOrderLine.objects.create(purchase_order=order, sku=sku, quantity_ordered=2, unit_cost="10")
        self.assertEqual(self.transition("archive").status_code, 200)
        edited = self.client.post(f"/api/purchase-orders/{order.pk}/edit/", {"purchaser": self.user.pk, "notes": "交接中，保留原归属", "lines": [{"sku": str(sku.pk), "quantity_ordered": "2", "unit_cost": "10"}]}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((order.purchaser_id, line.quantity_ordered, line.unit_cost), (self.user.pk, 2, 10))
        self.assertIn("已离职", edited.data["purchaser_display_name"])
        created = self.client.post("/api/purchase-orders/", {"number": "PO-NEW", "supplier": str(supplier.pk), "warehouse": str(self.warehouse.pk),
            "purchaser": self.user.pk, "lines": [{"sku": str(sku.pk), "quantity_ordered": "1", "unit_cost": "10"}]}, format="json")
        self.assertEqual(created.status_code, 400)

    def test_departure_cancels_paid_jobs_and_discards_processing_candidates(self):
        from unittest.mock import patch
        from apps.erp.models import AIProviderConfig
        from apps.erp.scheduling_models import ScheduleTerm, TimetableEvidence, TimetableImport, TimetableRecognitionJob
        from apps.erp.timetable_recognition import run_one_job, finish_job
        provider = AIProviderConfig.objects.create(organization=self.org, name="test", api_base_url="https://vision.invalid/v1", model_name="test", api_key_encrypted="test")
        term = ScheduleTerm.objects.create(organization=self.org, name="term", first_monday=timezone.localdate())
        evidence = TimetableEvidence.objects.create(organization=self.org, owner=self.user, uploaded_by=self.user, private_file="preserved.png", sha256="a" * 64, original_name="课表", content_type="image/png", size=10, pixel_width=1, pixel_height=1)
        imp = TimetableImport.objects.create(organization=self.org, owner=self.user, term=term, evidence=evidence, draft_grid=[], selected_weeks=[1])
        queued = TimetableRecognitionJob.objects.create(organization=self.org, timetable_import=imp, input_revision=1, provider=provider)
        processing = TimetableRecognitionJob.objects.create(organization=self.org, timetable_import=imp, input_revision=2, provider=provider, status="processing", lease_token=uuid.uuid4(), lease_until=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self.transition("archive").status_code, 200)
        with patch("apps.erp.timetable_recognition.invoke_vision") as invoke:
            self.assertFalse(run_one_job())
            invoke.assert_not_called()
        self.assertFalse(finish_job(processing, grid=[[{"status": "class"}]]))
        queued.refresh_from_db()
        processing.refresh_from_db()
        imp.refresh_from_db()
        self.assertEqual((queued.status, processing.status, imp.draft_grid), ("failed", "failed", []))
        self.assertEqual(self.transition("restore").status_code, 200)
        self.assertFalse(run_one_job())
