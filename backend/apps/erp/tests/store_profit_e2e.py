"""Full product form -> real HTTP -> PostgreSQL -> reload/profit browser test."""
import os
from pathlib import Path
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.http import HttpResponse
from django.test import LiveServerTestCase, override_settings
from django.urls import path
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from config.urls import urlpatterns as production_patterns
from apps.erp.models import Organization, Membership, Warehouse, Product, SKU, OwnStore, StoreProduct, ProductImage, ExchangeRateSnapshot

ROOT = Path(__file__).resolve().parents[4]
FILES = {'market-profit.js':'text/javascript', 'index.html':'text/html', 'app.js':'text/javascript', 'team.js':'text/javascript', 'scheduling.js':'text/javascript',
    'profit-calculator.js':'text/javascript', 'runtime-config.js':'text/javascript', 'styles.css':'text/css', 'scheduling.css':'text/css'}


def page(request, name='index.html'):
    if name not in FILES:
        return HttpResponse(status=404)
    content = (ROOT / name).read_text(encoding='utf-8')
    if name == 'index.html':
        content = content.replace('<head>', '<head><script>window.DONGBO_CONFIG={mode:"team",apiBase:"/api"};</script>')
    return HttpResponse(content, content_type=FILES[name])


urlpatterns = [path('', page), path('<str:name>', page), *production_patterns]


@skipUnless(connection.vendor == 'postgresql', 'Requires isolated PostgreSQL')
@override_settings(ROOT_URLCONF=__name__, SCHEDULING_ENABLED=False)
class StoreProfitBrowserTests(LiveServerTestCase):
    def test_save_two_stores_reload_update_and_profit(self):
        self._save_two_stores_reload_update_and_profit(Membership.Role.ADMIN)

    def test_default_buyer_saves_two_stores_reload_update_and_profit(self):
        self._save_two_stores_reload_update_and_profit(Membership.Role.BUYER)

    def _save_two_stores_reload_update_and_profit(self, role):
        org = Organization.objects.create(name='E2E', slug=settings.INTERNAL_ORGANIZATION_SLUG)
        user = get_user_model().objects.create_user(username=f'store-e2e-{role}')
        membership = Membership.objects.create(organization=org, user=user, role=role)
        warehouse = Warehouse.objects.create(organization=org, name='测试仓', code='TEST')
        membership.authorized_warehouses.add(warehouse)
        # An empty override list deliberately exercises the real default role
        # permissions: buyer has neither product_status nor profit_rules.
        self.assertEqual(membership.permissions, [])
        product = Product.objects.create(organization=org, name='测试帆布包', status='active', source_url='https://example.com/bag')
        sku = SKU.objects.create(organization=org, product=product, code='BAG-E2E', cost='18.90', currency='CNY',
            category_code='bag-womens-womens-tote-bags', packed_weight_g='200', default_creator_commission_percent='15')
        ProductImage.objects.create(product=product, url='https://example.com/bag.png')
        stores = [OwnStore.objects.create(organization=org, name=name) for name in ('马来一店完整名称', '马来二店完整名称')]
        ExchangeRateSnapshot.objects.create(organization=org, effective_date=timezone.localdate(), fetched_at=timezone.now(), myr_cny='1.68', myr_usd='0.235', source='test', is_current=True)
        env = dict(os.environ, STORE_TEST_URL=self.live_server_url, STORE_TEST_TOKEN=str(RefreshToken.for_user(user)),
            STORE_TEST_ORG=str(org.pk), STORE_TEST_WAREHOUSE=str(warehouse.pk), STORE_TEST_FIRST=str(stores[0].pk), STORE_TEST_SECOND=str(stores[1].pk))
        completed = subprocess.run([os.environ['NODE_EXECUTABLE'], str(ROOT / 'tests/browser/store-profit-live.test.mjs')], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=150)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        listings = StoreProduct.objects.filter(sku=sku)
        self.assertEqual(listings.count(), 2)
        self.assertEqual(str(listings.get(store=stores[0]).sale_price_myr), '99.90')
        self.assertEqual(str(listings.get(store=stores[0]).commission_override_percent), '0.00')
        self.assertEqual(str(listings.get(store=stores[1]).sale_price_myr), '89.90')
        self.assertIsNone(listings.get(store=stores[1]).commission_override_percent)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.ACTIVE)
