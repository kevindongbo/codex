from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.erp.models import Organization, Membership, Warehouse, Supplier, Product, SKU, StockLedger


class PurchaseTrackingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Tracking QA', slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.user = get_user_model().objects.create_user(username='tracking-qa')
        Membership.objects.create(organization=self.org, user=self.user, role=Membership.Role.ADMIN)
        self.warehouse = Warehouse.objects.create(organization=self.org, name='QA', code='QA')
        self.supplier = Supplier.objects.create(organization=self.org, name='QA', code='QA')
        product = Product.objects.create(organization=self.org, name='QA', status=Product.Status.ACTIVE)
        self.sku = SKU.objects.create(organization=self.org, product=product, code='QA')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.payload = {'number': 'QA-PO', 'supplier': str(self.supplier.pk), 'warehouse': str(self.warehouse.pk),
                        'lines': [{'sku': str(self.sku.pk), 'quantity_ordered': '10', 'unit_cost': '2'}]}
        created = self.client.post('/api/purchase-orders/', self.payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.url = f"/api/purchase-orders/{created.data['id']}/edit/"

    def test_blank_save_then_fill_both_tracking_fields_preserves_packages_and_stock(self):
        response = self.client.post(self.url, {**self.payload, 'shipments': [{'lines': []}, {'lines': []}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        packages = response.data['shipments']
        self.assertEqual(len(packages), 2)
        first, second = packages
        response = self.client.post(self.url, {**self.payload, 'shipments': [
            {'id': first['id'], 'domestic_tracking_number': 'CN-1', 'international_tracking_number': 'INT-SHARED', 'lines': []},
            {'id': second['id'], 'domestic_tracking_number': 'CN-2', 'international_tracking_number': 'INT-SHARED', 'lines': []},
        ]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({p['id'] for p in response.data['shipments']}, {first['id'], second['id']})
        self.assertEqual({p['international_tracking_number'] for p in response.data['shipments']}, {'INT-SHARED'})
        self.assertFalse(StockLedger.objects.exists())

    def test_legacy_number_not_reclassified_and_omitted_new_fields_preserved(self):
        response = self.client.post(self.url, {**self.payload, 'shipments': [{'tracking_number': 'LEGACY', 'domestic_tracking_number': 'CN', 'international_tracking_number': 'INT'}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        package = response.data['shipments'][0]
        response = self.client.post(self.url, {**self.payload, 'shipments': [{'id': package['id'], 'tracking_number': 'LEGACY'}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['shipments'][0]['domestic_tracking_number'], 'CN')
        self.assertEqual(response.data['shipments'][0]['international_tracking_number'], 'INT')
        self.assertEqual(response.data['shipments'][0]['tracking_number'], 'LEGACY')
