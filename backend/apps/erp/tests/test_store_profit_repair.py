from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.erp.models import (Membership, Organization, Product, SKU, OwnStore, StoreProduct,
    ExchangeRateSnapshot, ProfitCalculationWorkingConfig)
from apps.erp.profit_calculator import calculate_profit


class StoreProfitRepairTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='测试组织', slug='store-profit-repair')
        self.user = get_user_model().objects.create_user(username='store-profit-editor')
        Membership.objects.create(organization=self.org, user=self.user, role='admin')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.product = Product.objects.create(organization=self.org, name='商品', status='active')
        self.sku = SKU.objects.create(organization=self.org, product=self.product, code='BAG-001', cost='18.90', currency='CNY',
            category_code='bag-womens-womens-tote-bags', packed_weight_g='200', default_creator_commission_percent='15')
        self.stores = [OwnStore.objects.create(organization=self.org, name=name) for name in ('MY一店', 'MY二店')]
        ExchangeRateSnapshot.objects.create(organization=self.org, effective_date=timezone.localdate(), fetched_at=timezone.now(),
            myr_cny='1.68', myr_usd='0.235', source='test', is_current=True)
        self.url = f'/api/skus/{self.sku.pk}/store-products/'

    def row(self, index, price='79.90', commission=None):
        return dict(store=str(self.stores[index].pk), sale_price_myr=price, commission_override_percent=commission,
            include_in_list_calculation=True, product_url='')

    def test_save_reload_update_two_stores_and_authoritative_profit(self):
        response = self.client.put(self.url, {'items':[self.row(0, commission='0'), self.row(1, '89.90')]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        product = self.client.get(f'/api/products/{self.product.pk}/').data
        listings = product['skus'][0]['store_products']
        self.assertEqual(len(listings), 2)
        summary = self.client.get('/api/skus/profit-summary/').data[0]
        self.assertEqual(summary['calculable_store_count'], 2)
        first = next(row for row in summary['stores'] if row['store'] == str(self.stores[0].pk))
        expected = calculate_profit(dict(cny_per_myr=Decimal('1.68'), usd_per_myr=Decimal('0.235'), commission_adjustment=Decimal('1'),
            items=[dict(category_code=self.sku.category_code, weight_g=Decimal('200'), item_price=Decimal('79.90'), product_cost_cny=Decimal('18.90'), affiliate_rate=Decimal('0'))]))
        self.assertEqual(first['gross_profit'], expected['gross_profit'])
        self.assertEqual(first['break_even_roi'], expected['break_even_roi'])
        self.assertEqual(Decimal(first['commission_percent']), 0)
        response = self.client.put(self.url, {'items':[self.row(0, '99.90', '12'), self.row(1, '89.90')]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(StoreProduct.objects.get(sku=self.sku, store=self.stores[0]).sale_price_myr, Decimal('99.90'))

    def test_invalid_batch_is_atomic_and_cross_organization_is_rejected(self):
        self.client.put(self.url, {'items':[self.row(0)]}, format='json')
        invalid = self.client.put(self.url, {'items':[self.row(0, '999'), self.row(1, commission='101')]}, format='json')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertEqual(StoreProduct.objects.get().sale_price_myr, Decimal('79.90'))
        other = Organization.objects.create(name='其他组织', slug='store-profit-other')
        store = OwnStore.objects.create(organization=other, name='不可访问')
        row = self.row(0)
        row['store'] = str(store.pk)
        self.assertEqual(self.client.put(self.url, {'items':[row]}, format='json').status_code, 400)
        self.assertEqual(StoreProduct.objects.count(), 1)
        for value in ('invalid-uuid', None):
            row['store'] = value
            self.assertEqual(self.client.put(self.url, {'items':[row]}, format='json').status_code, 400)

    def test_incomplete_profit_keeps_saved_price_visible(self):
        self.sku.packed_weight_g = None
        self.sku.save()
        self.client.put(self.url, {'items':[self.row(0)]}, format='json')
        summary = self.client.get('/api/skus/profit-summary/').data[0]
        self.assertEqual(summary['sale_price']['min'], '79.90')
        self.assertEqual(summary['stores'][0]['missing'], ['包装重量'])
        self.assertIsNone(summary['break_even_roi'])

    def test_shared_manual_rates_work_without_external_rate_snapshot(self):
        ExchangeRateSnapshot.objects.all().delete()
        ProfitCalculationWorkingConfig.objects.create(organization=self.org, rate_mode='manual', manual_cny_per_myr='1.68', manual_usd_per_myr='0.235', config={'seller_type':'local'})
        self.client.put(self.url, {'items':[self.row(0)]}, format='json')
        summary = self.client.get('/api/skus/profit-summary/').data[0]
        self.assertEqual(summary['calculable_store_count'], 1)
        comparison = self.client.get(f'/api/skus/{self.sku.pk}/profit-comparison/').data
        self.assertEqual(comparison['stores'][0]['gross_profit'], summary['stores'][0]['gross_profit'])
