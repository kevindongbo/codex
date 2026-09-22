import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.erp.timetable_recognition import run_one_job


class Command(BaseCommand):
    help = 'Process private timetable vision jobs with DB leases; no automatic publication.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--poll-seconds', type=float, default=3)

    def handle(self, *args, **options):
        if not getattr(settings, 'SCHEDULING_ENABLED', False):
            raise CommandError('SCHEDULING_ENABLED is disabled')
        if not 1 <= options['poll_seconds'] <= 60:
            raise CommandError('--poll-seconds must be between 1 and 60')
        try:
            while True:
                worked = run_one_job()
                if options['once']:
                    return
                if not worked:
                    time.sleep(options['poll_seconds'])
        except KeyboardInterrupt:
            return
