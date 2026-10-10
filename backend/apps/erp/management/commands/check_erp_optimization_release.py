"""Read-only checks for the 2026-10-11 release; do not print private data."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from apps.erp.models import ProfitCalculationStrategy
from apps.erp.serializers import ProfitCalculationStrategySerializer


class Command(BaseCommand):
    help = 'Verify strategy storage and serialization without changing business data.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('Production checks require PostgreSQL.')
        table = ProfitCalculationStrategy._meta.db_table
        with connection.cursor() as cursor:
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                cursor.execute('SELECT has_table_privilege(current_user, %s, %s)', [table, privilege])
                if not cursor.fetchone()[0]:
                    raise CommandError(f'Strategy database role needs {privilege} on {table}.')
        count = 0
        for strategy in ProfitCalculationStrategy.objects.select_related('created_by', 'updated_by').iterator():
            try:
                dict(ProfitCalculationStrategySerializer(strategy).data)
            except Exception:
                raise CommandError('An existing strategy cannot be serialized. Preserve its data and inspect it privately.') from None
            count += 1
        self.stdout.write(f'Strategy permission/serialization checks passed ({count} records); no configuration values displayed.')
