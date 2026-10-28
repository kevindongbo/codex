from types import SimpleNamespace
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from importlib.util import module_from_spec, spec_from_file_location
from urllib.parse import urlsplit
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.erp.models import Organization, PurchaseOrder
from apps.erp.serializers import PurchaseOrderSerializer
from apps.erp.models import Membership, Supplier, Warehouse, Product, SKU, StockBalance


class PurchaseListInitializationTests(SimpleTestCase):
    def setUp(self):
        self.context = {"view": SimpleNamespace(organization=Organization())}

    def test_nonempty_paginated_list_initializes_without_reading_single_order(self):
        serializer = PurchaseOrderSerializer([PurchaseOrder(purchaser_id=1)], many=True, context=self.context)
        self.assertIn("purchaser", serializer.child.fields)

    def test_queryset_initialization_does_not_evaluate_database(self):
        serializer = PurchaseOrderSerializer(PurchaseOrder.objects.all(), many=True, context=self.context)
        self.assertIn("purchaser", serializer.child.fields)

    def test_single_order_keeps_original_purchaser_eligible(self):
        serializer = PurchaseOrderSerializer(PurchaseOrder(purchaser_id=123), context=self.context)
        self.assertIn("123", str(serializer.fields["purchaser"].queryset.query))


class PopulatedDashboardTests(TestCase):
    def test_dashboard_reads_nonempty_paginated_purchases_and_preserves_history(self):
        org = Organization.objects.create(name="测试", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        owner = get_user_model().objects.create_superuser(username="regression-owner", password="test-only-pass")
        buyer = get_user_model().objects.create_user(username="departed-buyer", is_active=False)
        Membership.objects.create(organization=org, user=owner, role="admin")
        Membership.objects.create(organization=org, user=buyer, active=False, employment_status="departed", display_name="原采购人")
        warehouse = Warehouse.objects.create(organization=org, code="W", name="原仓库")
        supplier = Supplier.objects.create(organization=org, code="S", name="原供应商")
        product = Product.objects.create(organization=org, name="原商品", status="active")
        sku = SKU.objects.create(organization=org, product=product, code="CAMERA", cost="10")
        balance = StockBalance.objects.create(organization=org, warehouse=warehouse, sku=sku, on_hand="17")
        orders = [PurchaseOrder.objects.create(organization=org, number="OLD-" + str(i),
                  warehouse=warehouse, supplier=supplier, purchaser=buyer) for i in range(2)]
        client = APIClient()
        client.force_authenticate(owner)
        for path in ("products", "purchase-orders", "stock-balances", "stores", "skus/profit-summary"):
            response = client.get("/api/" + path + "/")
            self.assertEqual(response.status_code, 200, path)
            if path == "purchase-orders":
                rows = response.data if isinstance(response.data, list) else response.data["results"]
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["purchaser_display_name"] == "原采购人（已离职）" for row in rows))
        balance.refresh_from_db()
        self.assertEqual(balance.on_hand, 17)
        self.assertEqual(PurchaseOrder.objects.filter(pk__in=[o.pk for o in orders], purchaser=buyer).count(), 2)
        self.assertEqual(Product.objects.filter(pk=product.pk).count(), 1)
        # Execute the deployed smoke probe against real Django views using its
        # actual freshly issued JWT, without exposing fixture records or tokens.
        spec = spec_from_file_location("dashboard_probe", settings.BASE_DIR.parent / "deploy" / "verify-dashboard-reads.py")
        probe = module_from_spec(spec)
        spec.loader.exec_module(probe)
        client.force_authenticate(user=None)
        paths = []
        def local_get(request, timeout):
            url = urlsplit(request.full_url)
            path = url.path + ("?" + url.query if url.query else "")
            paths.append(path)
            response = client.get(path, HTTP_AUTHORIZATION=request.get_header("Authorization"))
            self.assertEqual(response.status_code, 200, path)
            return BytesIO(response.content)
        output = StringIO()
        with patch("urllib.request.urlopen", side_effect=local_get), redirect_stdout(output):
            probe.verify()
        self.assertEqual(len(paths), 19)
        self.assertIn("AUTHENTICATED DASHBOARD READS VERIFIED", output.getvalue())
        self.assertNotIn("Bearer", output.getvalue())
