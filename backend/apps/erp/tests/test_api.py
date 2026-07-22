import hashlib
import hmac
import os
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib import admin
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.erp.apps import ErpConfig
from apps.erp import alphashop, integrations
from apps.erp.models import (
    AIProviderConfig, AIRecommendation, AlphaShopConfig, AuditLog, CompetitorProduct,
    CompetitorSnapshot, LocalImport, Membership, Organization,
    Product, ProductImage, PurchaseOrder, ReplenishmentPolicy, ReplenishmentSettings, ReturnOrder, SalesOrder,
    SalesOrderLine, Shipment, SKU, StockBalance, StockLedger, StockTransfer, TikTokShopConnection,
    TikTokShopOAuthState,
    Supplier, Warehouse,
)


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="api-user", password="test-pass-123")
        self.organization = Organization.objects.create(
            name="东铂", slug=settings.INTERNAL_ORGANIZATION_SLUG
        )
        Membership.objects.create(
            organization=self.organization, user=self.user, role=Membership.Role.ADMIN
        )
        self.client = APIClient()

    def test_health_is_public_and_checks_database(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_admin_hides_groups_and_internal_account_management(self):
        self.assertNotIn(Group, admin.site._registry)
        self.assertNotIn(get_user_model(), admin.site._registry)
        self.assertNotIn(Organization, admin.site._registry)
        self.assertNotIn(Membership, admin.site._registry)

    def test_internal_management_pages_use_chinese_labels(self):
        self.assertEqual(settings.LANGUAGE_CODE, "zh-hans")
        self.assertEqual(ErpConfig.verbose_name, "东铂跨境运营管理系统")
        self.assertEqual(admin.site.site_header, "东铂跨境运营管理后台")
        self.assertEqual(admin.site.site_title, "东铂跨境运营管理系统")
        self.assertEqual(admin.site.index_title, "系统管理")
        self.assertEqual(Warehouse._meta.verbose_name, "仓库")
        self.assertEqual(Product._meta.verbose_name, "商品")
        self.assertEqual(SKU._meta.verbose_name, "库存单位（SKU）")
        self.assertEqual(Supplier._meta.verbose_name, "供应商")

    def test_jwt_login(self):
        response = self.client.post(
            "/api/auth/token/", {"username": "api-user", "password": "test-pass-123"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["username"], "api-user")
        self.assertEqual(me.data["memberships"][0]["organization"]["name"], "东铂")

        self.client.credentials()
        rejected = self.client.post(
            "/api/auth/token/", {"username": "api-user", "password": "wrong-password"}, format="json"
        )
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.data["detail"], "账号名或密码错误，或账号已被停用")

        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        expired = self.client.get("/api/auth/me/")
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.data["detail"], "登录凭证无效或已过期，请重新登录")

    def test_organization_scope_and_role_header(self):
        self.client.force_authenticate(self.user)
        create = self.client.post(
            "/api/warehouses/",
            {"code": "CN-01", "name": "深圳仓", "country": "CN"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertEqual(create.status_code, 201, create.data)
        self.assertTrue(Warehouse.objects.filter(organization=self.organization, code="CN-01").exists())
        duplicate = self.client.post(
            "/api/warehouses/",
            {"code": "CN-01", "name": "重复仓", "country": "CN"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertIn(duplicate.status_code, {400, 409})

        other = Organization.objects.create(name="其他公司", slug="other")
        denied = self.client.get("/api/warehouses/", HTTP_X_ORGANIZATION_ID=str(other.pk))
        self.assertEqual(denied.status_code, 403)

    def test_internal_system_disables_creating_additional_organizations(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/organizations/",
            {"name": "新团队", "slug": "new-team", "active": True},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(Organization.objects.count(), 1)

    def test_team_frontend_fields_and_linked_monitoring_profile_round_trip(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        product = self.client.post(
            "/api/products/",
            {
                "name": "团队商品", "seller": "Dongbo MY", "market": "MY",
                "sales_currency": "MYR", "monitoring_enabled": True,
                "source_url": "https://example.com/product",
            },
            format="json", **headers,
        )
        self.assertEqual(product.status_code, 201, product.data)
        competitor = self.client.post(
            "/api/competitors/",
            {
                "name": "团队商品监控", "linked_product": product.data["id"],
                "kind": "direct", "platform": "own", "market": "MY",
                "url": "https://example.com/product", "image_url": "https://example.com/image.jpg",
                "currency": "MYR", "active": True,
            },
            format="json", **headers,
        )

        self.assertEqual(competitor.status_code, 201, competitor.data)
        saved_product = Product.objects.get(pk=product.data["id"])
        saved_profile = CompetitorProduct.objects.get(pk=competitor.data["id"])
        self.assertEqual(saved_product.seller, "Dongbo MY")
        self.assertEqual(saved_product.sales_currency, "MYR")
        self.assertTrue(saved_product.monitoring_enabled)
        self.assertEqual(saved_profile.linked_product, saved_product)
        self.assertEqual(saved_profile.market, "MY")

    def test_product_image_accepts_compressed_local_upload_for_team_sync(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        product = self.client.post(
            "/api/products/",
            {"name": "本地图片商品", "source_url": "https://example.com/product"},
            format="json", **headers,
        )
        self.assertEqual(product.status_code, 201, product.data)
        data_url = "data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAABwAQCdASoBAAEAAUAmJaQAA3AA"
        uploaded = self.client.post(
            "/api/product-images/",
            {"product": product.data["id"], "url": data_url, "alt": "本地图片", "position": 0},
            format="json", **headers,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.assertEqual(uploaded.data["url"], data_url)

        rejected = self.client.post(
            "/api/product-images/",
            {"product": product.data["id"], "url": "http://example.com/image.jpg", "position": 1},
            format="json", **headers,
        )
        self.assertEqual(rejected.status_code, 400)

    def test_competitor_local_image_upload_uses_formal_media_url(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        image = SimpleUploadedFile("competitor.png", b"fake-png-content", content_type="image/png")
        uploaded = self.client.post("/api/media-assets/", {"file": image}, **headers)
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.assertIn("/api/media-assets/", uploaded.data["url"])
        competitor = self.client.post(
            "/api/competitors/",
            {"name": "本地图片竞品", "url": "https://example.com/product", "image_url": uploaded.data["url"]},
            format="json", **headers,
        )
        self.assertEqual(competitor.status_code, 201, competitor.data)
        rejected = self.client.post(
            "/api/competitors/",
            {"name": "Base64 竞品", "url": "https://example.com/product", "image_url": "data:image/png;base64,AAAA"},
            format="json", **headers,
        )
        self.assertEqual(rejected.status_code, 400)

    def test_manual_stock_movement_revoke_and_zero_balance_delete(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(organization=self.organization, code="MANUAL-WH", name="手动出入库仓")
        product = Product.objects.create(organization=self.organization, name="手动库存商品", status=Product.Status.ACTIVE)
        sku = SKU.objects.create(organization=self.organization, product=product, code="MANUAL-SKU", cost="10")
        inbound = self.client.post(
            "/api/stock-balances/manual-inbound/",
            {"warehouse": str(warehouse.pk), "sku": str(sku.pk), "quantity": "5", "reason": "", "idempotency_key": "manual-in-1"},
            format="json", **headers,
        )
        self.assertEqual(inbound.status_code, 201, inbound.data)
        outbound = self.client.post(
            "/api/stock-balances/manual-outbound/",
            {"warehouse": str(warehouse.pk), "sku": str(sku.pk), "quantity": "5", "reason": "", "idempotency_key": "manual-out-1"},
            format="json", **headers,
        )
        self.assertEqual(outbound.status_code, 201, outbound.data)
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 0)
        reversal = self.client.post(f"/api/stock-ledger/{outbound.data['id']}/revoke/", {"reason": "录入错误"}, format="json", **headers)
        self.assertEqual(reversal.status_code, 200, reversal.data)
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 5)
        duplicate = self.client.post(f"/api/stock-ledger/{outbound.data['id']}/revoke/", {"reason": "重复"}, format="json", **headers)
        self.assertEqual(duplicate.status_code, 400)
        final_outbound = self.client.post(
            "/api/stock-balances/manual-outbound/",
            {"warehouse": str(warehouse.pk), "sku": str(sku.pk), "quantity": "5", "idempotency_key": "manual-out-2"},
            format="json", **headers,
        )
        self.assertEqual(final_outbound.status_code, 201, final_outbound.data)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.on_hand, 0)
        pending_order = SalesOrder.objects.create(
            organization=self.organization,
            number="SO-BLOCK-ZERO-BALANCE",
            warehouse=warehouse,
            status=SalesOrder.Status.READY,
        )
        SalesOrderLine.objects.create(order=pending_order, sku=sku, quantity="1")
        blocked = self.client.delete(f"/api/stock-balances/{balance.pk}/", **headers)
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertIn("待出库订单", str(blocked.data))
        pending_order.status = SalesOrder.Status.CANCELLED
        pending_order.save(update_fields=["status"])
        deleted = self.client.delete(f"/api/stock-balances/{balance.pk}/", **headers)
        self.assertEqual(deleted.status_code, 204)

    def test_force_delete_stock_balance_removes_nonzero_balance_and_ledger(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(organization=self.organization, code="PURGE-WH", name="purge warehouse")
        product = Product.objects.create(organization=self.organization, name="purge stock product", status=Product.Status.ACTIVE)
        sku = SKU.objects.create(organization=self.organization, product=product, code="PURGE-SKU", cost="10")
        inbound = self.client.post(
            "/api/stock-balances/manual-inbound/",
            {"warehouse": str(warehouse.pk), "sku": str(sku.pk), "quantity": "5", "idempotency_key": "purge-stock-1"},
            format="json", **headers,
        )
        self.assertEqual(inbound.status_code, 201, inbound.data)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        deleted = self.client.delete(f"/api/stock-balances/{balance.pk}/force-delete/", **headers)
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(StockBalance.objects.filter(pk=balance.pk).exists())
        self.assertFalse(StockLedger.objects.filter(sku=sku, warehouse=warehouse).exists())

    def test_inactive_product_force_delete_purges_business_records(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(organization=self.organization, code="PURGE-PROD-WH", name="purge product warehouse")
        supplier = Supplier.objects.create(organization=self.organization, code="PURGE-PROD-SUP", name="purge product supplier")
        product = Product.objects.create(organization=self.organization, name="inactive purge product", status=Product.Status.ACTIVE)
        sku = SKU.objects.create(organization=self.organization, product=product, code="PURGE-PROD-SKU", cost="8")
        balance = StockBalance.objects.create(organization=self.organization, warehouse=warehouse, sku=sku, on_hand="2")
        purchase = self.client.post(
            "/api/purchase-orders/",
            {"number": "PO-PURGE-PROD", "supplier": str(supplier.pk), "warehouse": str(warehouse.pk), "currency": "CNY",
             "lines": [{"sku": str(sku.pk), "quantity_ordered": "2", "unit_cost": "8"}]},
            format="json", **headers,
        )
        self.assertEqual(purchase.status_code, 201, purchase.data)
        product.status = Product.Status.INACTIVE
        product.save(update_fields=["status", "updated_at"])
        product_id, sku_id, balance_id = product.pk, sku.pk, balance.pk
        deleted = self.client.delete(f"/api/products/{product_id}/force-delete/", **headers)
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(Product.objects.filter(pk=product_id).exists())
        self.assertFalse(SKU.objects.filter(pk=sku_id).exists())
        self.assertFalse(StockBalance.objects.filter(pk=balance_id).exists())
        self.assertEqual(PurchaseOrder.objects.get(pk=purchase.data["id"]).lines.count(), 0)
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action="product.force_delete", object_id=str(product_id)).exists())

    def test_ai_provider_reports_deepseek_format_and_missing_encryption_key(self):
        owner = get_user_model().objects.create_superuser(username="owner-ai", password="test-pass-123", email="owner@example.com")
        self.client.force_authenticate(owner)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        anthopic_url = self.client.post(
            "/api/ai-providers/",
            {"name": "deepseek", "api_base_url": "https://api.deepseek.com/anthropic", "model_name": "deepseek-v4-flash", "api_key": "sk-test"},
            format="json", **headers,
        )
        self.assertEqual(anthopic_url.status_code, 400, anthopic_url.data)
        self.assertIn("api_base_url", anthopic_url.data)
        wrong_model = self.client.post(
            "/api/ai-providers/",
            {"name": "deepseek", "api_base_url": "https://api.deepseek.com", "model_name": "deepseek", "api_key": "sk-test"},
            format="json", **headers,
        )
        self.assertEqual(wrong_model.status_code, 400, wrong_model.data)
        with patch.dict(os.environ, {"INTEGRATION_ENCRYPTION_KEY": ""}, clear=False):
            no_key = self.client.post(
                "/api/ai-providers/",
                {"name": "valid-deepseek", "api_base_url": "https://api.deepseek.com", "model_name": "deepseek-v4-flash", "api_key": "sk-test"},
                format="json", **headers,
            )
        self.assertEqual(no_key.status_code, 400, no_key.data)
        self.assertIn("api_key", no_key.data)

    def test_ai_provider_accepts_safe_request_parameters_and_rejects_reserved_fields(self):
        owner = get_user_model().objects.create_superuser(
            username="owner-ai-parameters", password="test-pass-123", email="owner@example.com"
        )
        self.client.force_authenticate(owner)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        saved = self.client.post(
            "/api/ai-providers/",
            {
                "name": "parameterized-model", "api_base_url": "https://llm.example.com/v1",
                "model_name": "example-model", "api_key": "test-api-key",
                "default_parameters": {"temperature": 0.2, "max_tokens": 800},
            }, format="json", **headers,
        )
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["default_parameters"], {"temperature": 0.2, "max_tokens": 800})
        unsafe = self.client.post(
            "/api/ai-providers/",
            {
                "name": "unsafe-model", "api_base_url": "https://llm.example.com/v1",
                "model_name": "example-model", "api_key": "test-api-key",
                "default_parameters": {"messages": [{"role": "user", "content": "override"}]},
            }, format="json", **headers,
        )
        self.assertEqual(unsafe.status_code, 400, unsafe.data)
        self.assertIn("default_parameters", unsafe.data)

    def test_ai_recommendation_decisions_are_audited_and_never_post_inventory(self):
        owner = get_user_model().objects.create_superuser(
            username="owner-ai-workbench", password="test-pass-123", email="owner@example.com"
        )
        self.client.force_authenticate(owner)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        provider = AIProviderConfig.objects.create(
            organization=self.organization,
            name="workbench-provider",
            api_base_url="https://llm.example.com/v1",
            model_name="example-model",
            api_key_encrypted="encrypted-not-used-by-decision",
        )
        proposed = AIRecommendation.objects.create(
            organization=self.organization,
            provider=provider,
            kind=AIRecommendation.Kind.REPLENISHMENT,
            input_data={"sku": "demo"},
            proposal={"suggested_order_quantity": 12},
        )
        before_ledger_count = StockLedger.objects.filter(organization=self.organization).count()
        confirmed = self.client.post(
            f"/api/ai-recommendations/{proposed.pk}/confirm/",
            {"reason": "reviewed"}, format="json", **headers,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        proposed.refresh_from_db()
        self.assertEqual(proposed.status, AIRecommendation.Status.CONFIRMED)
        self.assertEqual(StockLedger.objects.filter(organization=self.organization).count(), before_ledger_count)
        self.assertTrue(AuditLog.objects.filter(
            organization=self.organization, action="ai.recommendation.confirm", object_id=str(proposed.pk)
        ).exists())
        repeated = self.client.post(
            f"/api/ai-recommendations/{proposed.pk}/confirm/", format="json", **headers,
        )
        self.assertEqual(repeated.status_code, 400, repeated.data)

        rejected = AIRecommendation.objects.create(
            organization=self.organization,
            provider=provider,
            kind=AIRecommendation.Kind.COPYWRITING,
            input_data={"title": "demo"},
            proposal={"copy": "demo copy"},
        )
        response = self.client.post(
            f"/api/ai-recommendations/{rejected.pk}/reject/",
            {"reason": "not suitable"}, format="json", **headers,
        )
        self.assertEqual(response.status_code, 200, response.data)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, AIRecommendation.Status.REJECTED)
        self.assertEqual(rejected.rejection_reason, "not suitable")
        self.assertTrue(AuditLog.objects.filter(
            organization=self.organization, action="ai.recommendation.reject", object_id=str(rejected.pk)
        ).exists())

    def test_ai_error_redaction_removes_provider_credentials(self):
        message = integrations._redact_provider_error(
            "provider returned Authorization: Bearer visible-token and key=exact-key",
            "exact-key",
        )
        self.assertNotIn("visible-token", message)
        self.assertNotIn("exact-key", message)
        self.assertIn("[REDACTED]", message)

    def test_viewer_cannot_modify_or_delete_organization(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="test-pass-123")
        Membership.objects.create(
            organization=self.organization, user=viewer, role=Membership.Role.VIEWER
        )
        self.client.force_authenticate(viewer)

        update = self.client.patch(
            f"/api/organizations/{self.organization.pk}/", {"active": False}, format="json"
        )
        destroy = self.client.delete(f"/api/organizations/{self.organization.pk}/")

        self.assertEqual(update.status_code, 403)
        self.assertEqual(destroy.status_code, 403)
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.active)

    def test_owner_manages_internal_accounts_and_child_logs_in_directly(self):
        owner = get_user_model().objects.create_superuser(
            username="owner", email="owner@example.com", password="Owner-pass-123!"
        )
        self.client.force_authenticate(owner)
        created = self.client.post(
            "/api/internal-accounts/",
            {
                "username": "warehouse-user",
                "password": "Child-pass-123!",
                "permissions": ["view", "warehouse"],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["permissions"], ["view", "warehouse"])
        self.assertTrue(AuditLog.objects.filter(
            organization=self.organization, action="account.create"
        ).exists())

        self.client.force_authenticate(user=None)
        token = self.client.post(
            "/api/auth/token/",
            {"username": "warehouse-user", "password": "Child-pass-123!"},
            format="json",
        )
        self.assertEqual(token.status_code, 200, token.data)
        self.assertIn("access", token.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200, me.data)
        self.assertEqual(len(me.data["memberships"]), 1)
        self.assertEqual(me.data["memberships"][0]["organization"]["id"], str(self.organization.pk))
        self.assertEqual(me.data["permissions"], ["view", "warehouse"])
        self.assertEqual(self.client.get("/api/internal-accounts/").status_code, 403)

        self.client.force_authenticate(owner)
        disabled = self.client.delete(f"/api/internal-accounts/{created.data['id']}/")
        self.assertEqual(disabled.status_code, 204)
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
        # SimpleJWT rejects tokens issued to an inactive account during
        # authentication, so the old token is invalidated with 401 before
        # the endpoint's permission check runs.
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(
            self.client.post(
                "/api/auth/token/",
                {"username": "warehouse-user", "password": "Child-pass-123!"},
                format="json",
            ).status_code,
            401,
        )

    @override_settings(
        OWNER_EMAIL_VERIFICATION_REQUIRED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    @patch("apps.erp.owner_security.send_mail")
    def test_only_owner_uses_email_verification_and_can_change_password(self, send_mail):
        owner = get_user_model().objects.create_superuser(
            username="mail-owner", email="owner@example.com", password="Original-pass-123!"
        )
        login = self.client.post(
            "/api/auth/token/",
            {"username": "mail-owner", "password": "Original-pass-123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.assertTrue(login.data["email_verification_required"])
        login_code = send_mail.call_args.args[1].split("：", 1)[1].split("\n", 1)[0]
        verified = self.client.post(
            "/api/auth/owner/login/verify/",
            {"challenge_id": login.data["challenge_id"], "code": login_code},
            format="json",
        )
        self.assertEqual(verified.status_code, 200, verified.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {verified.data['access']}")
        requested = self.client.post("/api/auth/owner/password/change/request/", format="json")
        self.assertEqual(requested.status_code, 200, requested.data)
        change_code = send_mail.call_args.args[1].split("：", 1)[1].split("\n", 1)[0]
        changed = self.client.post(
            "/api/auth/owner/password/change/confirm/",
            {
                "challenge_id": requested.data["challenge_id"],
                "code": change_code,
                "password": "Changed-pass-456!",
            },
            format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        owner.refresh_from_db()
        self.assertTrue(owner.check_password("Changed-pass-456!"))

        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.post("/api/auth/owner/password/change/request/", format="json").status_code,
            403,
        )

    def test_drafts_accept_incomplete_information_but_cannot_be_submitted(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        product = self.client.post("/api/products/", {}, format="json", **headers)
        warehouse = self.client.post("/api/warehouses/", {}, format="json", **headers)
        supplier = self.client.post("/api/suppliers/", {}, format="json", **headers)
        purchase = self.client.post("/api/purchase-orders/", {}, format="json", **headers)
        order = self.client.post("/api/orders/", {}, format="json", **headers)

        self.assertEqual(product.status_code, 201, product.data)
        self.assertEqual(product.data["name"], "待完善商品")
        self.assertEqual(warehouse.status_code, 201, warehouse.data)
        self.assertEqual(warehouse.data["name"], "待完善仓库")
        self.assertEqual(supplier.status_code, 201, supplier.data)
        self.assertEqual(supplier.data["name"], "待完善供应商")
        self.assertEqual(purchase.status_code, 201, purchase.data)
        self.assertEqual(purchase.data["status"], PurchaseOrder.Status.DRAFT)
        self.assertEqual(order.status_code, 201, order.data)
        self.assertEqual(order.data["status"], SalesOrder.Status.DRAFT)
        self.assertEqual(
            self.client.post(f"/api/purchase-orders/{purchase.data['id']}/submit/", **headers).status_code,
            400,
        )

    def test_sync_revision_increases_after_a_data_change(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        before = self.client.get("/api/sync/version/", **headers)
        self.assertEqual(before.status_code, 200, before.data)
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(
                "/api/products/", {"name": "同步测试商品"}, format="json", **headers
            )
        self.assertEqual(created.status_code, 201, created.data)
        after = self.client.get("/api/sync/version/", **headers)
        self.assertGreater(after.data["revision"], before.data["revision"])

    def test_related_objects_cannot_cross_organization_on_create_or_patch(self):
        self.client.force_authenticate(self.user)
        other = Organization.objects.create(name="其他公司", slug="tenant-other")
        other_product = Product.objects.create(organization=other, name="其他商品")
        other_supplier = Supplier.objects.create(
            organization=other, code="OTHER-SUP", name="其他供应商"
        )
        own_product = Product.objects.create(organization=self.organization, name="本组织商品")
        image = ProductImage.objects.create(
            product=own_product, url="https://example.com/own.jpg", position=0
        )

        create_sku = self.client.post(
            "/api/skus/",
            {"product": str(other_product.pk), "code": "CROSS-001", "cost": "1.00"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        patch_image = self.client.patch(
            f"/api/product-images/{image.pk}/",
            {"product": str(other_product.pk)},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        patch_product = self.client.patch(
            f"/api/products/{own_product.pk}/",
            {"default_supplier": str(other_supplier.pk)},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(create_sku.status_code, 400)
        self.assertEqual(patch_image.status_code, 400)
        self.assertEqual(patch_product.status_code, 400)
        self.assertFalse(SKU.objects.filter(organization=self.organization, code="CROSS-001").exists())
        image.refresh_from_db()
        self.assertEqual(image.product_id, own_product.pk)

    def test_sku_can_be_created_without_optional_barcode(self):
        self.client.force_authenticate(self.user)
        product = Product.objects.create(
            organization=self.organization, name="无条码商品"
        )

        response = self.client.post(
            "/api/skus/",
            {"product": str(product.pk), "code": "NO-BARCODE-001", "cost": "18.50"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["barcode"], "")

    def test_invalid_nested_purchase_does_not_leave_parent_record(self):
        self.client.force_authenticate(self.user)
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="CN-02", name="东莞仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="SUP-01", name="供应商"
        )
        other = Organization.objects.create(name="另一租户", slug="po-other")
        other_product = Product.objects.create(organization=other, name="其他商品")
        other_sku = SKU.objects.create(
            organization=other, product=other_product, code="OTHER-SKU", cost="5"
        )

        response = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-CROSS",
                "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk),
                "currency": "CNY",
                "lines": [{
                    "sku": str(other_sku.pk), "quantity_ordered": "2", "unit_cost": "5"
                }],
            },
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PurchaseOrder.objects.filter(number="PO-CROSS").exists())

    def test_product_activation_requires_link_image_sku_and_cost(self):
        self.client.force_authenticate(self.user)
        product = Product.objects.create(organization=self.organization, name="待完善商品")
        SKU.objects.create(
            organization=self.organization, product=product, code="DRAFT-SKU", cost="0"
        )
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}

        incomplete = self.client.post(f"/api/products/{product.pk}/activate/", **headers)
        self.assertEqual(incomplete.status_code, 400)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.DRAFT)

        product.source_url = "https://example.com/product"
        product.save(update_fields=["source_url", "updated_at"])
        ProductImage.objects.create(
            product=product, url="https://example.com/product.jpg", position=0
        )
        sku = product.skus.get()
        sku.cost = "12.50"
        sku.save(update_fields=["cost", "updated_at"])

        activated = self.client.post(f"/api/products/{product.pk}/activate/", **headers)
        self.assertEqual(activated.status_code, 200, activated.data)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.ACTIVE)

    def test_product_delete_removes_unreferenced_skus_and_zero_configuration(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="DELETE-WH", name="删除测试仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="可删除商品", status=Product.Status.ACTIVE
        )
        first_sku = SKU.objects.create(
            organization=self.organization, product=product, code="DELETE-SKU-A", cost="5"
        )
        second_sku = SKU.objects.create(
            organization=self.organization, product=product, code="DELETE-SKU-B", cost="6"
        )
        ProductImage.objects.create(
            product=product, url="https://example.com/delete.jpg", position=0
        )
        StockBalance.objects.create(
            organization=self.organization, warehouse=warehouse, sku=first_sku
        )
        ReplenishmentPolicy.objects.create(
            organization=self.organization, warehouse=warehouse, sku=second_sku
        )
        product_id = product.pk
        sku_ids = [first_sku.pk, second_sku.pk]

        response = self.client.delete(f"/api/products/{product_id}/", **headers)

        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(Product.objects.filter(pk=product_id).exists())
        self.assertFalse(SKU.objects.filter(pk__in=sku_ids).exists())
        self.assertFalse(StockBalance.objects.filter(sku_id__in=sku_ids).exists())
        self.assertFalse(ReplenishmentPolicy.objects.filter(sku_id__in=sku_ids).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                organization=self.organization,
                action="product.delete",
                object_id=str(product_id),
            ).exists()
        )

    def test_product_delete_rejects_inventory_and_business_history_atomically(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="PROTECT-WH", name="保护测试仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="PROTECT-SUP", name="保护测试供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="受保护商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="PROTECT-SKU", cost="8"
        )
        balance = StockBalance.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku, on_hand="2"
        )

        inventory_blocked = self.client.delete(f"/api/products/{product.pk}/", **headers)
        self.assertEqual(inventory_blocked.status_code, 400, inventory_blocked.data)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

        balance.on_hand = 0
        balance.save(update_fields=["on_hand", "updated_at"])
        policy = ReplenishmentPolicy.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku
        )
        purchase = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-PROTECT", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "currency": "CNY",
                "lines": [{"sku": str(sku.pk), "quantity_ordered": "2", "unit_cost": "8"}],
            },
            format="json", **headers,
        )
        self.assertEqual(purchase.status_code, 201, purchase.data)

        history_blocked = self.client.delete(f"/api/products/{product.pk}/", **headers)

        self.assertEqual(history_blocked.status_code, 400, history_blocked.data)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertTrue(SKU.objects.filter(pk=sku.pk).exists())
        self.assertTrue(StockBalance.objects.filter(pk=balance.pk).exists())
        self.assertTrue(ReplenishmentPolicy.objects.filter(pk=policy.pk).exists())

    def test_only_draft_purchase_orders_can_be_deleted(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="PO-DELETE-WH", name="采购删除测试仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="PO-DELETE-SUP", name="采购删除供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="采购删除商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="PO-DELETE-SKU", cost="9"
        )

        def create_purchase(number):
            return self.client.post(
                "/api/purchase-orders/",
                {
                    "number": number, "supplier": str(supplier.pk),
                    "warehouse": str(warehouse.pk), "currency": "CNY",
                    "lines": [{"sku": str(sku.pk), "quantity_ordered": "3", "unit_cost": "9"}],
                },
                format="json", **headers,
            )

        draft = create_purchase("PO-DELETE-DRAFT")
        self.assertEqual(draft.status_code, 201, draft.data)
        deleted = self.client.delete(
            f"/api/purchase-orders/{draft.data['id']}/", **headers
        )
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(PurchaseOrder.objects.filter(pk=draft.data["id"]).exists())
        self.assertTrue(SKU.objects.filter(pk=sku.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="purchase_order.delete", object_id=str(draft.data["id"])
            ).exists()
        )

        submitted = create_purchase("PO-DELETE-SUBMITTED")
        self.assertEqual(submitted.status_code, 201, submitted.data)
        submit = self.client.post(
            f"/api/purchase-orders/{submitted.data['id']}/submit/", **headers
        )
        self.assertEqual(submit.status_code, 200, submit.data)
        refused = self.client.delete(
            f"/api/purchase-orders/{submitted.data['id']}/", **headers
        )
        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertTrue(PurchaseOrder.objects.filter(pk=submitted.data["id"]).exists())

    def test_purchase_and_order_actions_enforce_state_and_release_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="FLOW-WH", name="流程仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="FLOW-SUP", name="流程供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="流程商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="FLOW-SKU", cost="8"
        )

        purchase = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-FLOW", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "currency": "CNY",
                "lines": [{"sku": str(sku.pk), "quantity_ordered": "3", "unit_cost": "8"}],
            },
            format="json", **headers,
        )
        self.assertEqual(purchase.status_code, 201, purchase.data)
        purchase_id = purchase.data["id"]
        submitted = self.client.post(f"/api/purchase-orders/{purchase_id}/submit/", **headers)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], PurchaseOrder.Status.SUBMITTED)
        self.assertEqual(submitted.data["in_transit_quantity"], "3.000")
        balances = self.client.get("/api/stock-balances/", **headers)
        self.assertEqual(balances.status_code, 200)
        self.assertEqual(balances.data["results"][0]["on_hand"], "0.000")
        self.assertEqual(balances.data["results"][0]["in_transit"], 3)

        adjusted = self.client.post(
            "/api/stock-balances/adjust/",
            {
                "warehouse": str(warehouse.pk), "sku": str(sku.pk), "delta": "5",
                "reason": "测试期初库存", "idempotency_key": "api-flow-opening",
            },
            format="json", **headers,
        )
        self.assertEqual(adjusted.status_code, 201, adjusted.data)

        order = self.client.post(
            "/api/orders/",
            {
                "number": "SO-FLOW", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        self.assertEqual(order.status_code, 201, order.data)
        order_id = order.data["id"]
        confirmed = self.client.post(f"/api/orders/{order_id}/confirm/", **headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        other_warehouse = Warehouse.objects.create(
            organization=self.organization, code="OTHER-WH", name="其他仓"
        )
        frozen = self.client.patch(
            f"/api/orders/{order_id}/", {"warehouse": str(other_warehouse.pk)},
            format="json", **headers,
        )
        self.assertEqual(frozen.status_code, 400)

        allocated = self.client.post(
            f"/api/orders/{order_id}/allocate/",
            {"idempotency_key": "api-flow-allocate"}, format="json", **headers,
        )
        self.assertEqual(allocated.status_code, 200, allocated.data)
        picking = self.client.post(f"/api/orders/{order_id}/start-picking/", **headers)
        self.assertEqual(picking.status_code, 200, picking.data)
        self.assertEqual(picking.data["status"], SalesOrder.Status.PICKING)
        verified = self.client.post(f"/api/orders/{order_id}/verify/", **headers)
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data["status"], SalesOrder.Status.VERIFIED)
        cancelled = self.client.post(f"/api/orders/{order_id}/cancel/", **headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], SalesOrder.Status.CANCELLED)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.reserved, 0)

    def test_one_receipt_posts_all_selected_purchase_lines_atomically(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="BATCH-RECEIVE", name="批量收货仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="BATCH-SUP", name="批量供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="批量收货商品", status=Product.Status.ACTIVE
        )
        first_sku = SKU.objects.create(
            organization=self.organization, product=product, code="BATCH-SKU-1", cost="8"
        )
        second_sku = SKU.objects.create(
            organization=self.organization, product=product, code="BATCH-SKU-2", cost="12"
        )
        purchase = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-BATCH-RECEIVE", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "currency": "CNY",
                "lines": [
                    {"sku": str(first_sku.pk), "quantity_ordered": "3", "unit_cost": "8"},
                    {"sku": str(second_sku.pk), "quantity_ordered": "5", "unit_cost": "12"},
                ],
            },
            format="json", **headers,
        )
        self.assertEqual(purchase.status_code, 201, purchase.data)
        purchase_id = purchase.data["id"]
        submitted = self.client.post(f"/api/purchase-orders/{purchase_id}/submit/", **headers)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        line_ids = {str(line["sku"]): line["id"] for line in submitted.data["lines"]}
        payload = {
            "purchase_order": purchase_id,
            "number": "GRN-BATCH-RECEIVE",
            "idempotency_key": "batch-receive-001",
            "lines": [
                {"purchase_line": line_ids[str(first_sku.pk)], "quantity": "3", "unit_cost": "8"},
                {"purchase_line": line_ids[str(second_sku.pk)], "quantity": "5", "unit_cost": "12"},
            ],
        }
        received = self.client.post("/api/receipts/", payload, format="json", **headers)
        self.assertEqual(received.status_code, 201, received.data)
        self.assertEqual(len(received.data["lines"]), 2)
        self.assertEqual(
            PurchaseOrder.objects.get(pk=purchase_id).status,
            PurchaseOrder.Status.RECEIVED,
        )
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=first_sku).on_hand, 3)
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=second_sku).on_hand, 5)
        replay = self.client.post("/api/receipts/", payload, format="json", **headers)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(replay.data["id"], received.data["id"])
        self.assertEqual(StockLedger.objects.filter(
            organization=self.organization, event_type=StockLedger.Type.RECEIPT
        ).count(), 2)

    def test_purchase_tracking_supports_split_receipts_and_purchaser(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="TRACK-WH", name="物流跟踪仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="TRACK-SUP", name="物流供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="物流跟踪商品", status=Product.Status.ACTIVE
        )
        first_sku = SKU.objects.create(
            organization=self.organization, product=product, code="TRACK-SKU-1", cost="8"
        )
        second_sku = SKU.objects.create(
            organization=self.organization, product=product, code="TRACK-SKU-2", cost="12"
        )
        buyer = get_user_model().objects.create_user(username="tracking-buyer", password="test-pass-123")
        Membership.objects.create(
            organization=self.organization, user=buyer, role=Membership.Role.BUYER,
            display_name="采购小王",
        )
        created = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-TRACK-SPLIT", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "purchaser": buyer.pk,
                "lines": [
                    {"sku": str(first_sku.pk), "quantity_ordered": "3", "unit_cost": "8"},
                    {"sku": str(second_sku.pk), "quantity_ordered": "5", "unit_cost": "12"},
                ],
            },
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["purchaser_display_name"], "采购小王")
        edited = self.client.post(
            f"/api/purchase-orders/{created.data['id']}/edit/",
            {
                "number": "PO-TRACK-SPLIT", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "purchaser": buyer.pk,
                "lines": [
                    {"sku": str(first_sku.pk), "quantity_ordered": "3", "unit_cost": "8"},
                    {"sku": str(second_sku.pk), "quantity_ordered": "5", "unit_cost": "12"},
                ],
                "shipments": [
                    {"tracking_number": "YT-ONE", "lines": [{"sku": str(first_sku.pk), "quantity_shipped": "3"}]},
                    {"tracking_number": "YT-TWO", "lines": [{"sku": str(second_sku.pk), "quantity_shipped": "5"}]},
                ],
            },
            format="json", **headers,
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(len(edited.data["shipments"]), 2)
        submitted = self.client.post(f"/api/purchase-orders/{created.data['id']}/submit/", **headers)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        line_ids = {str(line["sku"]): line["id"] for line in submitted.data["lines"]}
        package_one = next(item for item in submitted.data["shipments"] if item["tracking_number"] == "YT-ONE")
        rejected = self.client.post(
            "/api/receipts/",
            {
                "purchase_order": created.data["id"], "purchase_shipment": package_one["id"],
                "number": "GRN-TRACK-BAD", "idempotency_key": "track-bad",
                "lines": [{"purchase_line": line_ids[str(second_sku.pk)], "quantity": "1"}],
            },
            format="json", **headers,
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        received = self.client.post(
            "/api/receipts/",
            {
                "purchase_order": created.data["id"], "purchase_shipment": package_one["id"],
                "number": "GRN-TRACK-ONE", "idempotency_key": "track-one",
                "lines": [{"purchase_line": line_ids[str(first_sku.pk)], "quantity": "3"}],
            },
            format="json", **headers,
        )
        self.assertEqual(received.status_code, 201, received.data)
        self.assertEqual(PurchaseOrder.objects.get(pk=created.data["id"]).status, PurchaseOrder.Status.PARTIAL)

    def test_warehouse_member_cannot_write_outside_authorized_warehouse(self):
        warehouse_allowed = Warehouse.objects.create(
            organization=self.organization, code="ACCESS-YES", name="授权仓"
        )
        warehouse_denied = Warehouse.objects.create(
            organization=self.organization, code="ACCESS-NO", name="未授权仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="仓库授权商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(organization=self.organization, product=product, code="ACCESS-SKU", cost="5")
        supplier = Supplier.objects.create(organization=self.organization, code="ACCESS-SUP", name="授权供应商")
        operator = get_user_model().objects.create_user(username="warehouse-access", password="test-pass-123")
        membership = Membership.objects.create(
            organization=self.organization, user=operator, role=Membership.Role.BUYER,
        )
        membership.authorized_warehouses.add(warehouse_allowed)
        self.client.force_authenticate(operator)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        denied = self.client.post(
            "/api/purchase-orders/",
            {"number": "PO-DENIED", "supplier": str(supplier.pk), "warehouse": str(warehouse_denied.pk),
             "lines": [{"sku": str(sku.pk), "quantity_ordered": "1", "unit_cost": "5"}]},
            format="json", **headers,
        )
        self.assertEqual(denied.status_code, 403, denied.data)
        allowed = self.client.post(
            "/api/purchase-orders/",
            {"number": "PO-ALLOWED", "supplier": str(supplier.pk), "warehouse": str(warehouse_allowed.pk),
             "lines": [{"sku": str(sku.pk), "quantity_ordered": "1", "unit_cost": "5"}]},
            format="json", **headers,
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_return_must_reference_shipped_quantity_and_support_partial_receipt(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RETURN-WH", name="退货仓"
        )
        product = Product.objects.create(organization=self.organization, name="退货商品")
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="RETURN-SKU", cost="10"
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-RETURN-API", warehouse=warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        SalesOrderLine.objects.create(
            order=order, sku=sku, quantity="2", quantity_shipped="2", unit_price="20"
        )

        excessive = self.client.post(
            "/api/returns/",
            {
                "number": "RET-TOO-MUCH", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "3", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(excessive.status_code, 400)

        rejected = self.client.post(
            "/api/returns/",
            {
                "number": "RET-REJECT", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "1", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(rejected.status_code, 201, rejected.data)
        rejected_result = self.client.post(
            f"/api/returns/{rejected.data['id']}/reject/", **headers
        )
        self.assertEqual(rejected_result.status_code, 200)
        self.assertEqual(rejected_result.data["status"], ReturnOrder.Status.REJECTED)

        created = self.client.post(
            "/api/returns/",
            {
                "number": "RET-API", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "2", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        return_id = created.data["id"]
        line_id = created.data["lines"][0]["id"]
        partial = self.client.post(
            f"/api/returns/{return_id}/receive/",
            {"idempotency_key": "return-api-1", "lines": [{"return_line": line_id, "quantity": "1"}]},
            format="json", **headers,
        )
        self.assertEqual(partial.status_code, 200, partial.data)
        self.assertEqual(partial.data["status"], ReturnOrder.Status.PARTIAL)
        self.assertEqual(len(partial.data["receipts"]), 1)

    def test_receive_from_order_is_atomic_and_idempotent(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RETURN-COMBO", name="组合退货仓"
        )
        product = Product.objects.create(organization=self.organization, name="组合退货商品")
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="RETURN-COMBO-SKU", cost="10"
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-RETURN-COMBO", warehouse=warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        SalesOrderLine.objects.create(
            order=order, sku=sku, quantity="2", quantity_shipped="2", unit_price="20"
        )
        payload = {
            "idempotency_key": "return-combo-key",
            "number": "RET-COMBO", "original_order": str(order.pk),
            "warehouse": str(warehouse.pk), "reason": "完好退回",
            "lines": [{
                "sku": str(sku.pk), "quantity_expected": "2",
                "condition": "restock", "unit_refund": "0",
            }],
        }

        first = self.client.post(
            "/api/returns/receive-from-order/", payload, format="json", **headers
        )
        repeated = self.client.post(
            "/api/returns/receive-from-order/", payload, format="json", **headers
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(first.data["id"], repeated.data["id"])
        self.assertEqual(ReturnOrder.objects.filter(number="RET-COMBO").count(), 1)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.on_hand, 2)

    def test_local_backup_preview_and_commit_import_catalog_snapshot_and_opening_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="DEFAULT", name="默认仓"
        )
        source = {
            "version": 5,
            "products": [
                {
                    "id": "local-own", "name": "本店商品", "kind": "own", "sku": "LOCAL-001",
                    "seller": "Dongbo", "market": "MY", "salesCurrency": "MYR",
                    "costCurrency": "CNY", "standardCost": 12.5, "safetyStock": 3,
                    "defaultSupplier": "迁移供应商", "status": "active",
                    "productUrl": "https://example.com/own", "purchaseUrl": "https://example.com/buy",
                    "image": "https://example.com/own.jpg", "monitoringEnabled": False,
                },
                {
                    "id": "local-competitor", "name": "竞品", "kind": "direct", "sku": "",
                    "seller": "Other", "market": "MY", "salesCurrency": "MYR", "status": "active",
                    "productUrl": "https://example.com/competitor",
                    "image": "https://example.com/competitor.jpg", "monitoringEnabled": True,
                },
            ],
            "snapshots": [{
                "id": "local-snapshot", "productId": "local-competitor",
                "at": "2026-07-15T00:00:00Z", "price": 19.9, "sold": 10,
                "rating": 4.8, "reviews": 5, "lowReviews": 1, "shopRating": 4.7,
            }],
            "inventoryBalances": [{
                "productId": "local-own", "onHand": 7, "reserved": 0,
            }],
            "purchaseOrders": [{"id": "archived-po"}],
            "salesOrders": [], "returns": [], "inventoryMovements": [],
        }

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "local-import-test",
            },
            format="json", **headers,
        )
        repeated = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "local-import-test",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(preview.data["summary"]["products"], 2)
        self.assertTrue(any("历史采购" in item for item in preview.data["warnings"]))
        self.assertEqual(committed.status_code, 201, committed.data)
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(committed.data["id"], repeated.data["id"])
        self.assertEqual(LocalImport.objects.count(), 1)
        self.assertEqual(Product.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(CompetitorProduct.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(CompetitorSnapshot.objects.count(), 1)
        sku = SKU.objects.get(organization=self.organization, code="LOCAL-001")
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 7)

    def _local_import_source(self, *, products=None, snapshots=None, balances=None):
        return {
            "version": 5,
            "products": products or [],
            "snapshots": snapshots or [],
            "inventoryBalances": balances or [],
            "purchaseOrders": [],
            "salesOrders": [],
            "returns": [],
            "inventoryMovements": [],
        }

    def test_local_import_sanitizes_unsafe_urls_and_keeps_product_draft(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-URL", name="导入仓"
        )
        source = self._local_import_source(products=[
            {
                "id": "unsafe-own", "name": "不安全链接商品", "kind": "own",
                "sku": "UNSAFE-001", "standardCost": "10", "status": "active",
                "productUrl": "https://user:secret@example.com/item",
                "purchaseUrl": "javascript:alert(1)",
                "image": "http://example.com/not-shared.jpg",
            },
            {
                "id": "unsafe-competitor", "name": "无效竞品", "kind": "direct",
                "productUrl": "javascript:alert(1)",
                "image": "https://example.com/competitor.jpg",
            },
        ])

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "unsafe-url-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(committed.status_code, 201, committed.data)
        product = Product.objects.get(organization=self.organization)
        self.assertEqual(product.status, Product.Status.DRAFT)
        self.assertEqual(product.source_url, "")
        self.assertEqual(product.purchase_url, "")
        self.assertFalse(product.images.exists())
        self.assertFalse(CompetitorProduct.objects.filter(organization=self.organization).exists())

    def test_local_import_rejects_malformed_source_without_partial_rows(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-BAD", name="校验仓"
        )
        source = self._local_import_source(
            products=[{"id": None, "name": None, "kind": "own", "sku": None}],
            snapshots=[{"id": "bad-snapshot", "productId": None, "at": "not-a-date"}],
            balances=[{"productId": None, "onHand": 1, "reserved": 0}],
        )

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "bad-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["ready"])
        self.assertEqual(committed.status_code, 400, committed.data)
        self.assertFalse(Product.objects.filter(organization=self.organization).exists())
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_local_import_rolls_back_catalog_when_opening_stock_fails(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-ROLLBACK", name="回滚仓"
        )
        source = self._local_import_source(
            products=[{
                "id": "rollback-own", "name": "回滚商品", "kind": "own",
                "sku": "ROLLBACK-001", "standardCost": "8", "status": "active",
                "productUrl": "https://example.com/rollback",
                "image": "https://example.com/rollback.jpg",
                "defaultSupplier": "回滚供应商",
            }],
            balances=[{"productId": "rollback-own", "onHand": 2, "reserved": 0}],
        )

        with patch(
            "apps.erp.local_imports.adjust_inventory",
            side_effect=DjangoValidationError("模拟库存过账失败"),
        ):
            response = self.client.post(
                "/api/local-imports/commit/",
                {
                    "warehouse": str(warehouse.pk), "source": source,
                    "idempotency_key": "rollback-import",
                },
                format="json", **headers,
            )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Product.objects.filter(organization=self.organization).exists())
        self.assertFalse(Supplier.objects.filter(organization=self.organization).exists())
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_local_import_idempotency_is_warehouse_bound_and_keys_fit_database(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-IDEM-A", name="幂等仓 A"
        )
        other_warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-IDEM-B", name="幂等仓 B"
        )
        source = self._local_import_source(
            products=[{
                "id": "idem-own", "name": "幂等商品", "kind": "own",
                "sku": "IDEM-001", "standardCost": "5", "status": "active",
                "productUrl": "https://example.com/idem",
                "image": "https://example.com/idem.jpg",
            }],
            balances=[{"productId": "idem-own", "onHand": 1, "reserved": 0}],
        )
        idempotency_key = "k" * 160

        too_long = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "x" * 161,
            },
            format="json", **headers,
        )
        first = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": idempotency_key,
            },
            format="json", **headers,
        )
        wrong_warehouse = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(other_warehouse.pk), "source": source,
                "idempotency_key": idempotency_key,
            },
            format="json", **headers,
        )

        self.assertEqual(too_long.status_code, 400, too_long.data)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(wrong_warehouse.status_code, 400, wrong_warehouse.data)
        ledger = StockLedger.objects.get(organization=self.organization)
        self.assertLessEqual(len(ledger.reference_id), 64)
        self.assertLessEqual(len(ledger.idempotency_key), 160)
        report = LocalImport.objects.get(organization=self.organization)
        with self.assertRaises(DjangoValidationError):
            report.delete()
        with self.assertRaises(DjangoValidationError):
            LocalImport.objects.filter(pk=report.pk).update(status="completed")

    def test_local_import_write_actions_require_manager_role(self):
        viewer = get_user_model().objects.create_user(
            username="import-viewer", password="test-pass-123"
        )
        Membership.objects.create(
            organization=self.organization, user=viewer, role=Membership.Role.VIEWER
        )
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-VIEW", name="只读仓"
        )
        self.client.force_authenticate(viewer)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        source = self._local_import_source()

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "viewer-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 403)
        self.assertEqual(committed.status_code, 403)

    def test_local_import_blocks_open_documents_and_reserved_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-OPEN", name="开放单据仓"
        )
        source = self._local_import_source(
            products=[{
                "id": "open-own", "name": "开放单据商品", "kind": "own",
                "sku": "OPEN-001", "standardCost": "5", "status": "active",
                "productUrl": "https://example.com/open",
                "image": "https://example.com/open.jpg",
            }],
            balances=[{"productId": "open-own", "onHand": 3, "reserved": 1}],
        )
        source.update({
            "purchaseOrders": [{"id": "po-open", "status": "transit"}],
            "salesOrders": [{"id": "so-open", "status": "picking"}],
            "returns": [{"id": "ret-open", "status": "partial"}],
            "reservations": [{"id": "res-open", "status": "active"}],
        })

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "open-state-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["ready"])
        self.assertTrue(any("锁定库存" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成采购单" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成订单" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成退货单" in error for error in preview.data["errors"]))
        self.assertEqual(committed.status_code, 400, committed.data)
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_custom_warehouse_types_and_replenishment_policy_are_tenant_scoped(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        created_ids = []
        for code, name, warehouse_type, country, timezone_name in [
            ("MY", "马来仓", "overseas", "my", "Asia/Kuala_Lumpur"),
            ("FWD", "货代仓", "forwarder", "CN", "Asia/Shanghai"),
            ("SCHOOL", "学校仓", "school", "CN", "Asia/Shanghai"),
        ]:
            response = self.client.post(
                "/api/warehouses/",
                {
                    "code": code, "name": name, "warehouse_type": warehouse_type,
                    "country": country, "timezone": timezone_name,
                    "address": {"city": "测试城市"},
                    "contact": {"name": "仓管", "phone": "123"},
                    "can_receive": True, "can_ship": code != "FWD",
                },
                format="json", **headers,
            )
            self.assertEqual(response.status_code, 201, response.data)
            created_ids.append(response.data["id"])
        self.assertEqual(Warehouse.objects.filter(organization=self.organization).count(), 3)
        malaysia = Warehouse.objects.get(pk=created_ids[0])
        self.assertEqual(malaysia.country, "MY")
        self.assertEqual(malaysia.warehouse_type, Warehouse.Type.OVERSEAS)
        self.assertEqual(malaysia.timezone, "Asia/Kuala_Lumpur")

        product = Product.objects.create(
            organization=self.organization, name="补货商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="REPLENISH-SKU", cost="8"
        )
        policy = self.client.post(
            "/api/replenishment-policies/",
            {
                "warehouse": str(malaysia.pk), "sku": str(sku.pk),
                "lead_time_override": 12, "review_cycle_days": 7, "target_days": 35,
                "min_order_qty": "10", "pack_size": "5",
                "safety_stock_override": "8",
            },
            format="json", **headers,
        )
        self.assertEqual(policy.status_code, 201, policy.data)
        self.assertEqual(ReplenishmentPolicy.objects.get().lead_time_override, 12)

        other = Organization.objects.create(name="策略其他组织", slug="policy-other")
        other_warehouse = Warehouse.objects.create(
            organization=other, code="OTHER", name="其他仓"
        )
        cross_org = self.client.post(
            "/api/replenishment-policies/",
            {
                "warehouse": str(other_warehouse.pk), "sku": str(sku.pk),
                "review_cycle_days": 7, "target_days": 30,
                "min_order_qty": "1", "pack_size": "1",
            },
            format="json", **headers,
        )
        self.assertEqual(cross_org.status_code, 400)
        self.assertEqual(ReplenishmentPolicy.objects.count(), 1)

    def test_stock_transfer_api_tracks_in_transit_and_prevents_reposting(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        source = Warehouse.objects.create(
            organization=self.organization, code="TRANSFER-SRC", name="学校仓",
            warehouse_type=Warehouse.Type.SCHOOL,
        )
        destination = Warehouse.objects.create(
            organization=self.organization, code="TRANSFER-DST", name="马来仓",
            warehouse_type=Warehouse.Type.OVERSEAS, country="MY",
        )
        product = Product.objects.create(
            organization=self.organization, name="调拨商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="TRANSFER-SKU", cost="10"
        )
        opening = self.client.post(
            "/api/stock-balances/adjust/",
            {
                "warehouse": str(source.pk), "sku": str(sku.pk), "delta": "6",
                "reason": "调拨测试期初", "idempotency_key": "api-transfer-opening",
            },
            format="json", **headers,
        )
        self.assertEqual(opening.status_code, 201, opening.data)
        created = self.client.post(
            "/api/stock-transfers/",
            {
                "number": "TR-API-001", "source_warehouse": str(source.pk),
                "destination_warehouse": str(destination.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "4"}],
            },
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        transfer_id = created.data["id"]
        first_dispatch = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-001"}, format="json", **headers,
        )
        replay_dispatch = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-001"}, format="json", **headers,
        )
        wrong_replay = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-other"}, format="json", **headers,
        )
        self.assertEqual(first_dispatch.status_code, 200, first_dispatch.data)
        self.assertEqual(replay_dispatch.status_code, 200, replay_dispatch.data)
        self.assertEqual(wrong_replay.status_code, 400)
        self.assertEqual(first_dispatch.data["status"], StockTransfer.Status.IN_TRANSIT)
        self.assertEqual(StockBalance.objects.get(warehouse=source, sku=sku).on_hand, 2)
        destination_balance = StockBalance.objects.get(warehouse=destination, sku=sku)
        balances = self.client.get("/api/stock-balances/", **headers)
        destination_row = next(
            row for row in balances.data["results"]
            if row["id"] == str(destination_balance.pk)
        )
        self.assertEqual(destination_row["in_transit"], 4)
        recommendations = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={destination.pk}", **headers
        )
        self.assertEqual(recommendations.status_code, 200, recommendations.data)
        self.assertEqual(recommendations.data[0]["inventory"]["in_transit"], 4)
        refused_delete = self.client.delete(
            f"/api/stock-transfers/{transfer_id}/", **headers
        )
        self.assertEqual(refused_delete.status_code, 400)

        first_receive = self.client.post(
            f"/api/stock-transfers/{transfer_id}/receive/",
            {"idempotency_key": "api-receive-001"}, format="json", **headers,
        )
        replay_receive = self.client.post(
            f"/api/stock-transfers/{transfer_id}/receive/",
            {"idempotency_key": "api-receive-001"}, format="json", **headers,
        )
        self.assertEqual(first_receive.status_code, 200, first_receive.data)
        self.assertEqual(replay_receive.status_code, 200, replay_receive.data)
        destination_balance.refresh_from_db()
        self.assertEqual(destination_balance.on_hand, 4)
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.TRANSFER_OUT).count(), 1
        )
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.TRANSFER_IN).count(), 1
        )

    def test_replenishment_recommendations_apply_policy_and_scope_warehouse(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RECOMMEND", name="建议仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="建议商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="REC-SKU", cost="6"
        )
        policy = ReplenishmentPolicy.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku,
            lead_time_override=12, review_cycle_days=7, target_days=30,
            min_order_qty="10", pack_size="5", safety_stock_override="5",
        )
        inactive_product = Product.objects.create(
            organization=self.organization, name="停用商品", status=Product.Status.INACTIVE
        )
        SKU.objects.create(
            organization=self.organization, product=inactive_product,
            code="INACTIVE-REC", cost="2",
        )

        response = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={warehouse.pk}", **headers
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        recommendation = response.data[0]
        self.assertEqual(recommendation["sku"], str(sku.pk))
        self.assertEqual(recommendation["policy"], str(policy.pk))
        self.assertEqual(recommendation["lead_time"]["selected_days"], 12)
        self.assertEqual(recommendation["suggested_order_quantity"], 10)
        self.assertTrue(recommendation["needs_reorder"])
        self.assertEqual(recommendation["alert_level"], "red")

        other = Organization.objects.create(name="建议其他组织", slug="recommend-other")
        other_warehouse = Warehouse.objects.create(
            organization=other, code="OTHER-REC", name="其他建议仓"
        )
        denied = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={other_warehouse.pk}",
            **headers,
        )
        self.assertEqual(denied.status_code, 400)

    def test_replenishment_settings_are_saved_per_organization_and_validate_weights(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        saved = self.client.post(
            "/api/replenishment-settings/",
            {
                "safety_days": "9.5", "default_lead_time_days": 21, "review_cycle_days": 5,
                "target_days": 35, "service_level_factor": "1.96", "safety_margin_ratio": "0.25", "initial_reference_shipment_count": 4,
                "velocity_weight_7": "0.6", "velocity_weight_15": "0.3", "velocity_weight_30": "0.1",
            }, format="json", **headers,
        )
        self.assertEqual(saved.status_code, 201, saved.data)
        settings_record = ReplenishmentSettings.objects.get(organization=self.organization)
        self.assertEqual(str(settings_record.safety_days), "9.50")
        self.assertEqual(settings_record.default_lead_time_days, 21)
        self.assertEqual(settings_record.safety_margin_ratio, Decimal("0.250"))
        invalid = self.client.post(
            "/api/replenishment-settings/",
            {"velocity_weight_3": 0, "velocity_weight_7": 0, "velocity_weight_15": 0, "velocity_weight_30": 0},
            format="json", **headers,
        )
        self.assertEqual(invalid.status_code, 400)
        invalid_margin = self.client.patch(
            f"/api/replenishment-settings/{settings_record.pk}/",
            {"safety_margin_ratio": "1.1"}, format="json", **headers,
        )
        self.assertEqual(invalid_margin.status_code, 400)

    def test_replenishment_batch_policy_only_overwrites_selected_fields(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(organization=self.organization, code="BATCH-REC", name="批量补货仓")
        first = Product.objects.create(organization=self.organization, name="批量补货 A", status=Product.Status.ACTIVE)
        second = Product.objects.create(organization=self.organization, name="批量补货 B", status=Product.Status.ACTIVE)
        first_sku = SKU.objects.create(organization=self.organization, product=first, code="BATCH-REC-A", cost="8")
        second_sku = SKU.objects.create(organization=self.organization, product=second, code="BATCH-REC-B", cost="9")
        saved = self.client.post(
            "/api/replenishment/batch-policy/",
            {
                "warehouse": str(warehouse.pk),
                "sku_ids": [str(first_sku.pk), str(second_sku.pk)],
                "fields": {"review_cycle_days": 9, "pack_size": "6"},
            },
            format="json", **headers,
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["updated"], 2)
        policies = ReplenishmentPolicy.objects.filter(organization=self.organization, warehouse=warehouse).order_by("sku__code")
        self.assertEqual([item.review_cycle_days for item in policies], [9, 9])
        self.assertEqual([item.pack_size for item in policies], [Decimal("6.000"), Decimal("6.000")])
        self.assertEqual([item.target_days for item in policies], [30, 30])

        recompute = self.client.post(
            "/api/replenishment/recompute/",
            {"warehouse": str(warehouse.pk), "sku_ids": [str(first_sku.pk)]},
            format="json", **headers,
        )
        self.assertEqual(recompute.status_code, 200, recompute.data)
        self.assertEqual(recompute.data["queued_skus"], 1)

    def test_tiktok_signature_uses_current_us_host_and_seller_shop_rows(self):
        params = {"app_key": "app-key", "timestamp": "1720000000"}
        expected_payload = "app-secret/authorization/202309/shopsapp_keyapp-keytimestamp1720000000app-secret"
        expected = hmac.new(b"app-secret", expected_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(
            integrations._tiktok_signature(
                path="/authorization/202309/shops", params=params, app_secret="app-secret"
            ), expected,
        )
        self.assertEqual(integrations.TIKTOK_AUTH_URLS["US"], "https://services.us.tiktokshop.com/open/authorize")

    @patch("apps.erp.integrations._get_tiktok_authorized_shops")
    @patch("apps.erp.integrations._exchange_tiktok_token")
    def test_tiktok_authorization_creates_one_encrypted_connection_per_shop(self, exchange_token, get_shops):
        state = "seller-state"
        TikTokShopOAuthState.objects.create(
            organization=self.organization, state_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(),
            redirect_uri="https://erp.example.com/api/integrations/tiktok-shop/callback/", region="MY",
            expires_at=timezone.now() + timedelta(minutes=10), created_by=self.user,
        )
        exchange_token.return_value = {
            "open_id": "seller-open-id", "user_type": 0, "access_token": "access-token-secret",
            "refresh_token": "refresh-token-secret", "access_token_expire_in": 3600,
            "refresh_token_expire_in": 86400, "granted_scopes": ["seller.authorization.info"],
        }
        get_shops.return_value = [
            {"id": "shop-my-1", "name": "马来一店", "region": "MY", "cipher": "cipher-1"},
            {"id": "shop-my-2", "name": "马来二店", "region": "MY", "cipher": "cipher-2"},
        ]
        connections = integrations.complete_tiktok_authorization(state=state, auth_code="test-code", actor=self.user)
        self.assertEqual(len(connections), 2)
        self.assertEqual(TikTokShopConnection.objects.filter(organization=self.organization).count(), 2)
        self.assertEqual({item.shop_id for item in connections}, {"shop-my-1", "shop-my-2"})
        self.assertTrue(all(item.shop_name for item in connections))
        self.assertTrue(all("access-token-secret" not in item.access_token_encrypted for item in connections))
        exchange_token.return_value = {
            "access_token": "rotated-access-token", "refresh_token": "rotated-refresh-token",
            "access_token_expire_in": 7200, "refresh_token_expire_in": 172800,
            "granted_scopes": ["seller.authorization.info"],
        }
        integrations.refresh_tiktok_connection(connections[0])
        for connection in TikTokShopConnection.objects.filter(organization=self.organization):
            self.assertNotIn("rotated-access-token", connection.access_token_encrypted)
            self.assertEqual(connection.status, TikTokShopConnection.Status.CONNECTED)

    def test_confirm_and_ship_api_is_atomic_and_idempotent(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="ONE-STEP", name="一键出库仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="一键商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="ONE-STEP-SKU", cost="9"
        )
        StockBalance.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku, on_hand="5"
        )
        order = self.client.post(
            "/api/orders/",
            {
                "number": "SO-ONE-STEP-API", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        self.assertEqual(order.status_code, 201, order.data)
        payload = {
            "idempotency_key": "confirm-ship-api-001", "tracking_number": "MY123"
        }
        first = self.client.post(
            f"/api/orders/{order.data['id']}/confirm-and-ship/",
            payload, format="json", **headers,
        )
        replay = self.client.post(
            f"/api/orders/{order.data['id']}/confirm-and-ship/",
            payload, format="json", **headers,
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 2)

        shortage = self.client.post(
            "/api/orders/",
            {
                "number": "SO-SHORTAGE-API", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        failed = self.client.post(
            f"/api/orders/{shortage.data['id']}/confirm-and-ship/",
            {"idempotency_key": "confirm-ship-shortage"}, format="json", **headers,
        )
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertEqual(
            SalesOrder.objects.get(pk=shortage.data["id"]).status, SalesOrder.Status.DRAFT
        )
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.on_hand, 2)
        self.assertEqual(balance.reserved, 0)

    def test_quick_sales_api_inherits_latest_snapshot_and_requires_history(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        competitor = CompetitorProduct.objects.create(
            organization=self.organization, name="快照竞品", url="https://example.com/quick"
        )
        missing = self.client.post(
            "/api/competitor-snapshots/quick-sales/",
            {"product": str(competitor.pk), "sold_count": 11}, format="json", **headers,
        )
        self.assertEqual(missing.status_code, 400)
        original = CompetitorSnapshot.objects.create(
            product=competitor, captured_at="2026-07-14T08:00:00Z", price="29.90",
            sold_count=10, rating="4.70", review_count=20,
            availability="available", raw={"low_reviews": 2, "shop_rating": 4.8},
        )
        quick = self.client.post(
            "/api/competitor-snapshots/quick-sales/",
            {"product": str(competitor.pk), "sold_count": 15}, format="json", **headers,
        )
        self.assertEqual(quick.status_code, 201, quick.data)
        self.assertEqual(quick.data["sold_count"], 15)
        self.assertEqual(quick.data["price"], "29.9000")
        self.assertEqual(quick.data["rating"], "4.70")
        self.assertEqual(quick.data["review_count"], 20)
        self.assertEqual(quick.data["availability"], "available")
        self.assertEqual(quick.data["raw"], original.raw)

    def test_local_import_preview_accepts_version_six(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-V6", name="第六版导入仓"
        )
        source = self._local_import_source()
        source["version"] = 6
        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source}, format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "version-six-import",
            },
            format="json", **headers,
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(preview.data["summary"]["source_version"], 6)
        self.assertEqual(committed.status_code, 201, committed.data)
        self.assertEqual(committed.data["source_version"], 6)

    @override_settings(ALPHASHOP_ACCESS_KEY="", ALPHASHOP_SECRET_KEY="")
    def test_product_selection_status_never_exposes_credentials(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/product-selection/status/",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["configured"])
        self.assertEqual(response.data["defaults"], {"platform": "tiktok", "region": "MY", "listing_time": "90"})
        self.assertNotIn("access_key", response.data)
        self.assertNotIn("secret_key", response.data)

    @patch("apps.erp.views.alphashop.search_keywords")
    def test_product_selection_keyword_search_uses_authenticated_server_proxy(self, search_keywords):
        self.client.force_authenticate(self.user)
        search_keywords.return_value = {
            "keywords": [{"keyword": "women bag", "oppScore": 88}],
            "cached": False,
        }
        response = self.client.post(
            "/api/product-selection/keywords/",
            {"platform": "tiktok", "region": "my", "keyword": "bag", "listing_time": "90"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["keywords"][0]["keyword"], "women bag")
        search_keywords.assert_called_once_with(
            platform="tiktok", region="MY", keyword="bag", listing_time="90", organization=self.organization,
        )

    @patch.dict(os.environ, {"INTEGRATION_ENCRYPTION_KEY": "6WYxq_NVKo0Eq8o3EoYh5uEVEGTN8KlPJbwc_EW8ujY="})
    def test_owner_can_save_encrypted_alphashop_config_without_key_echo(self):
        owner = get_user_model().objects.create_superuser(
            username="selection-owner", email="owner@example.com", password="test-pass-123"
        )
        self.client.force_authenticate(owner)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        response = self.client.put(
            "/api/alphashop-config/",
            {
                "access_key": "owner-access-key",
                "secret_key": "owner-secret-key",
                "api_base_url": "https://api.alphashop.cn",
                "enabled": True,
            },
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["configured"])
        self.assertEqual(response.data["source"], "system")
        self.assertNotIn("access_key", response.data)
        self.assertNotIn("secret_key", response.data)
        config = AlphaShopConfig.objects.get(organization=self.organization)
        self.assertNotIn("owner-access-key", config.access_key_encrypted)
        self.assertNotIn("owner-secret-key", config.secret_key_encrypted)

        self.client.force_authenticate(self.user)
        denied = self.client.get("/api/alphashop-config/", **headers)
        self.assertEqual(denied.status_code, 403, denied.data)

    @patch("apps.erp.views.alphashop.generate_report")
    def test_product_selection_report_validates_filters_and_forwards_selected_keyword(self, generate_report):
        self.client.force_authenticate(self.user)
        generate_report.return_value = {
            "keyword_summary": {"summary": "机会良好"},
            "products": [{"productId": "123", "title": "Test product"}],
            "cached": False,
        }
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        invalid = self.client.post(
            "/api/product-selection/report/",
            {
                "platform": "tiktok", "region": "MY", "keyword": "women bag", "listing_time": "90",
                "min_price": 100, "max_price": 10,
            },
            format="json", **headers,
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
        valid = self.client.post(
            "/api/product-selection/report/",
            {
                "platform": "tiktok", "region": "MY", "keyword": "women bag", "listing_time": "90",
                "min_price": 10, "max_price": 100, "min_volume": 50, "min_rating": 4,
            },
            format="json", **headers,
        )
        self.assertEqual(valid.status_code, 200, valid.data)
        self.assertEqual(valid.data["products"][0]["productId"], "123")
        self.assertEqual(generate_report.call_args.kwargs["keyword"], "women bag")
        self.assertEqual(generate_report.call_args.kwargs["region"], "MY")

    def test_product_selection_rejects_unsupported_region_and_read_only_member(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        unsupported = self.client.post(
            "/api/product-selection/keywords/",
            {"platform": "amazon", "region": "MY", "keyword": "bag"},
            format="json", **headers,
        )
        self.assertEqual(unsupported.status_code, 400, unsupported.data)

        viewer = get_user_model().objects.create_user(username="selection-viewer", password="test-pass-123")
        Membership.objects.create(organization=self.organization, user=viewer, role=Membership.Role.VIEWER)
        self.client.force_authenticate(viewer)
        denied = self.client.post(
            "/api/product-selection/keywords/",
            {"platform": "tiktok", "region": "MY", "keyword": "bag"},
            format="json", **headers,
        )
        self.assertEqual(denied.status_code, 403, denied.data)

    @patch("apps.erp.views.alphashop.search_keywords", side_effect=RuntimeError("unexpected upstream state"))
    def test_product_selection_unexpected_error_is_safe_json_not_html_500(self, _search_keywords):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/product-selection/keywords/",
            {"platform": "tiktok", "region": "MY", "keyword": "women bag", "listing_time": "90"},
            format="json", HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data["code"], "ALPHASHOP_UNEXPECTED_ERROR")
        self.assertIn("选品查询暂时失败", response.data["detail"])
        self.assertNotIn("unexpected upstream state", response.data["detail"])

    @override_settings(
        ALPHASHOP_ACCESS_KEY="test-access-key",
        ALPHASHOP_SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
        ALPHASHOP_API_BASE="https://api.alphashop.cn",
        ALPHASHOP_KEYWORD_CACHE_SECONDS=60,
    )
    @patch("apps.erp.alphashop.urlopen")
    def test_alphashop_client_signs_server_request_and_normalizes_keywords(self, mocked_urlopen):
        response = MagicMock()
        response.read.return_value = b'{"success":true,"code":"SUCCESS","data":{"keywordList":[{"keyword":"bag"}]}}'
        mocked_urlopen.return_value.__enter__.return_value = response
        result = alphashop.search_keywords(
            platform="tiktok", region="MY", keyword="unique-test-bag", listing_time="90"
        )
        self.assertEqual(result["keywords"], [{"keyword": "bag"}])
        request = mocked_urlopen.call_args.args[0]
        self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
        self.assertNotIn("test-secret-key-that-is-long-enough-for-hs256", request.get_header("Authorization"))
        self.assertEqual(request.full_url, "https://api.alphashop.cn/opp.selection.keyword.search/1.0")

    @override_settings(
        ALPHASHOP_ACCESS_KEY="test-access-key",
        ALPHASHOP_SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
        ALPHASHOP_API_BASE="https://api.alphashop.cn",
    )
    @patch("apps.erp.alphashop.urlopen", side_effect=OSError("TLS connection reset"))
    def test_alphashop_network_failure_has_safe_diagnosis(self, _urlopen):
        with self.assertRaises(alphashop.AlphaShopError) as captured:
            alphashop.search_keywords(platform="tiktok", region="MY", keyword="safe-test-bag")
        self.assertEqual(captured.exception.code, "ALPHASHOP_TIMEOUT")
        self.assertNotIn("TLS connection reset", captured.exception.detail)
