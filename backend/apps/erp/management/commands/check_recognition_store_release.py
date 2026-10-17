from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from apps.erp.models import (
    AIInvocationLog, AIProviderConfig, AuditLog, OrganizationSyncState,
    OwnStore, Product, ProductImage, SKU, StoreProduct,
)
from apps.erp.serializers import StoreProductSerializer
from apps.erp.scheduling_models import (
    ScheduleTerm, TimetableEvidence, TimetableImport, TimetableRecognitionJob,
)


REQUIRED_TABLE_PRIVILEGES = (
    (Product, ('SELECT', 'INSERT', 'UPDATE', 'DELETE')),
    (SKU, ('SELECT', 'INSERT', 'UPDATE', 'DELETE')),
    (StoreProduct, ('SELECT', 'INSERT', 'UPDATE', 'DELETE')),
    (ProductImage, ('SELECT', 'INSERT', 'UPDATE', 'DELETE')),
    (OwnStore, ('SELECT',)),
    (AuditLog, ('INSERT',)),
    (OrganizationSyncState, ('SELECT', 'INSERT', 'UPDATE')),
    (TimetableEvidence, ('SELECT',)),
    (TimetableImport, ('SELECT', 'INSERT', 'UPDATE')),
    (TimetableRecognitionJob, ('SELECT', 'INSERT', 'UPDATE')),
    (AIProviderConfig, ('SELECT',)),
    (AIInvocationLog, ('INSERT',)),
)


class Command(BaseCommand):
    help = '只读核验课表识别和商品店铺修复发布，不调用付费模型。'

    def check_write_privileges(self):
        if connection.vendor != 'postgresql':
            self.stdout.write('POSTGRESQL TABLE PRIVILEGES NOT CHECKED (non-PostgreSQL database).')
            return
        missing = []
        try:
            with connection.cursor() as cursor:
                for model, privileges in REQUIRED_TABLE_PRIVILEGES:
                    table = model._meta.db_table
                    for privilege in privileges:
                        # Check each privilege separately: a comma-separated
                        # PostgreSQL privilege list succeeds if any one is held.
                        cursor.execute(
                            'SELECT has_table_privilege(current_user, %s, %s)',
                            [table, privilege],
                        )
                        row = cursor.fetchone()
                        if not row or row[0] is not True:
                            missing.append(f'{table}: {privilege}')
        except DatabaseError as exc:
            raise CommandError('无法只读核验 PostgreSQL 表权限，请确认发布涉及表存在且当前数据库账号可访问。') from exc
        if missing:
            raise CommandError('当前数据库账号缺少发布所需表权限：' + '; '.join(missing))
        self.stdout.write('POSTGRESQL TABLE PRIVILEGES OK (required privileges checked individually per table; no writes performed).')

    def handle(self, *args, **options):
        budget = getattr(settings, 'SCHEDULING_RECOGNITION_HOURLY_LIMIT', 60)
        if type(budget) is not int or budget < 1:
            raise CommandError('识别调用预算无效：SCHEDULING_RECOGNITION_HOURLY_LIMIT 必须为正整数。')
        self.check_write_privileges()
        # Exercise DB access and real serializers, but never print user rows.
        list(StoreProductSerializer(StoreProduct.objects.select_related('store', 'sku')[:5], many=True).data)
        enabled = AIProviderConfig.objects.filter(enabled=True).count()
        configured = ScheduleTerm.objects.filter(recognition_provider__enabled=True).count()
        self.stdout.write(f'STORE SERIALIZATION / CONFIG OK; scheduling_enabled={settings.SCHEDULING_ENABLED}; hourly_limit={budget}; enabled_providers={enabled}; configured_terms={configured}')
        self.stdout.write('Serialization/configuration/privileges checked only. No paid API calls or data writes; real image recognition still requires verify_timetable_recognition and human review.')
