"""Fail-closed release checks. Never print database credentials or private data."""
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = 'Validate scheduling migration scope and storage before release.'

    def add_arguments(self, parser):
        parser.add_argument('--expect-migrated', action='store_true')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('Release requires PostgreSQL.')
        if not settings.SCHEDULING_ENABLED:
            raise CommandError('Scheduling flag is disabled.')
        root = Path(settings.SCHEDULING_PRIVATE_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        if not root.is_dir() or root == media or media in root.parents:
            raise CommandError('Private storage must exist outside public media.')
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        allowed = {('erp', '0038_course_work_scheduling')}
        if any(backwards or (m.app_label, m.name) not in allowed for m, backwards in plan):
            raise CommandError('Unrelated migrations pending; stop and review separately.')
        if options['expect_migrated'] and plan:
            raise CommandError('Scheduling migration still pending.')
        with connection.cursor() as cursor:
            if plan:
                cursor.execute('SELECT has_schema_privilege(current_user, current_schema(), %s)', ['CREATE'])
                if not cursor.fetchone()[0]:
                    raise CommandError('Migration role needs CREATE in the current schema.')
                for table in ('erp_organization', 'auth_user', 'erp_aiproviderconfig'):
                    cursor.execute('SELECT has_table_privilege(current_user, %s, %s)', [table, 'REFERENCES'])
                    if not cursor.fetchone()[0]:
                        raise CommandError(f'Migration role needs REFERENCES on {table}.')
            else:
                from apps.erp.scheduling_models import ScheduleTerm, WorkScheduleCell, TimetableRecognitionJob
                for model in (ScheduleTerm, WorkScheduleCell, TimetableRecognitionJob):
                    model.objects.exists()
        self.stdout.write('Scheduling release checks passed; no credentials displayed.')
