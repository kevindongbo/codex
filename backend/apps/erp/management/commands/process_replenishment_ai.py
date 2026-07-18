from django.core.management.base import BaseCommand

from apps.erp.replenishment_automation import process_due_replenishment_ai_jobs


class Command(BaseCommand):
    help = "Process due, warehouse-scoped replenishment AI jobs. Run once per minute via systemd timer."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        count = process_due_replenishment_ai_jobs(limit=max(1, options["limit"]))
        self.stdout.write(self.style.SUCCESS(f"processed={count}"))
