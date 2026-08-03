from django.core.management.base import BaseCommand
from django.db import connection

from apps.erp.exchange_rates import refresh_snapshot
from apps.erp.models import Organization


LOCK_ID = 202608040900


class Command(BaseCommand):
    help = "Refresh durable MYR exchange-rate snapshots for active organizations."

    def handle(self, *args, **options):
        locked = True
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
                locked = cursor.fetchone()[0]
        if not locked:
            self.stdout.write("another exchange-rate refresh is already running")
            return
        try:
            for organization in Organization.objects.filter(active=True).order_by("id"):
                snapshot, failures = refresh_snapshot(organization, respect_manual=True)
                if snapshot:
                    self.stdout.write(self.style.SUCCESS(f"{organization.pk}: {snapshot.source} {snapshot.effective_date}"))
                else:
                    self.stderr.write(f"{organization.pk}: all sources failed ({', '.join(failures)})")
        finally:
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
