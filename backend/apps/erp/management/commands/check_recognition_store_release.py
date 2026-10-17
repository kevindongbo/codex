from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.erp.models import AIProviderConfig, StoreProduct
from apps.erp.serializers import StoreProductSerializer
from apps.erp.timetable_recognition import hourly_limit
from apps.erp.scheduling_models import ScheduleTerm


class Command(BaseCommand):
    help = '只读核验课表识别和商品店铺修复发布，不调用付费模型。'

    def handle(self, *args, **options):
        if hourly_limit() < 1:
            raise CommandError('识别调用预算无效')
        # Exercise DB access and real serializers, but never print user rows.
        list(StoreProductSerializer(StoreProduct.objects.select_related('store', 'sku')[:5], many=True).data)
        enabled = AIProviderConfig.objects.filter(enabled=True).count()
        configured = ScheduleTerm.objects.filter(recognition_provider__enabled=True).count()
        self.stdout.write(f'STORE SERIALIZATION OK; scheduling_enabled={settings.SCHEDULING_ENABLED}; hourly_limit={hourly_limit()}; enabled_providers={enabled}; configured_terms={configured}')
        self.stdout.write('No paid API calls; real image recognition requires verify_timetable_recognition and human review.')
