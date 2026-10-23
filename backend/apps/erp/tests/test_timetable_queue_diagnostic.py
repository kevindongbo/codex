"""Run the shipped diagnostic against PostgreSQL; reject writes and row locks."""
import copy
import io
import json
import re
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.erp.models import AIProviderConfig, Organization
from apps.erp.scheduling_models import (
    ScheduleTerm, TimetableEvidence, TimetableImport, TimetableRecognitionJob,
)


@skipUnless(connection.vendor == 'postgresql', 'Queue diagnostics target PostgreSQL')
@override_settings(SCHEDULING_ENABLED=True, SCHEDULING_RECOGNITION_HOURLY_LIMIT=3)
class TimetableQueueDiagnosticTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Queue test', slug='queue-diagnostic-test')
        self.user = get_user_model().objects.create_user(username='queue-diagnostic-user')
        self.provider = AIProviderConfig.objects.create(organization=self.org, name='Test vision',
            api_base_url='https://vision.example/v1', model_name='test-vision', api_key_encrypted='synthetic-encrypted')
        self.term = ScheduleTerm.objects.create(organization=self.org, name='Test term',
            first_monday=date(2026, 9, 21), recognition_provider=self.provider)
        self.evidence = TimetableEvidence.objects.create(organization=self.org, owner=self.user,
            uploaded_by=self.user, private_file='diagnostic-test.png', sha256='a' * 64,
            original_name='diagnostic-test.png', content_type='image/png', size=100,
            pixel_width=10, pixel_height=10)
        self.grid = [[{'status': 'unknown', 'course_name': ''} for _ in range(12)] for _ in range(7)]
        self.queued = self.new_job(status='queued', attempts=0,
            available_at=timezone.now() - timedelta(seconds=5))

    def new_job(self, **options):
        imp = TimetableImport.objects.create(organization=self.org, owner=self.user,
            term=self.term, evidence=self.evidence, selected_weeks=[1],
            draft_grid=copy.deepcopy(self.grid), revision=4)
        return TimetableRecognitionJob.objects.create(organization=self.org,
            timetable_import=imp, input_revision=4, provider=self.provider, **options)

    @staticmethod
    def snapshots():
        return {
            'imports': list(TimetableImport.objects.order_by('id').values()),
            'jobs': list(TimetableRecognitionJob.objects.order_by('id').values()),
        }

    def diagnose(self):
        script = Path(__file__).resolve().parents[4] / 'deploy' / 'diagnose-timetable-queue.sh'
        text = script.read_text(encoding='utf-8')
        opener = "<<'QUEUE_PY'\n"
        self.assertIn(opener, text)
        self.assertIn('\nQUEUE_PY\n', text)
        code = text.split(opener, 1)[1].split('\nQUEUE_PY\n', 1)[0]
        before = self.snapshots()
        statements = []

        def only_select(execute, sql, params, many, context):
            self.assertRegex(sql, r'^\s*SELECT\b', 'Diagnostic must execute SELECT statements only')
            self.assertIsNone(re.search(r'\bFOR\s+(?:(?:NO\s+KEY|KEY)\s+)?(?:UPDATE|SHARE)\b',
                sql, re.IGNORECASE), 'Diagnostic must not claim or lock rows')
            statements.append(sql)
            return execute(sql, params, many, context)

        output = io.StringIO()
        with connection.execute_wrapper(only_select), redirect_stdout(output):
            exec(compile(code, str(script) + '#QUEUE_PY', 'exec'), {})
        self.assertTrue(statements, 'Execute the real diagnostic queries rather than an empty fragment')
        self.assertEqual(self.snapshots(), before, 'Diagnostic must preserve all draft and job fields')
        raw = output.getvalue()
        records = {}
        for line in raw.splitlines():
            label, separator, payload = line.partition('=')
            self.assertEqual(separator, '=')
            records[label] = json.loads(payload)
        self.assertNotIn('queue_diagnostic_failed', records)
        self.assertTrue(records['runtime']['postgresql'])
        self.assertTrue(records['runtime']['scheduling_enabled'])
        self.assertTrue(records['worker_database_privileges'])
        self.assertTrue(all(row['allowed'] for row in records['worker_database_privileges']))
        return records, raw

    @staticmethod
    def job_record(records, job):
        return next(row for row in records['recent_jobs'] if row['job_id'] == str(job.pk))

    def test_idle_queued_job_is_eligible_without_being_claimed(self):
        records, _ = self.diagnose()
        self.assertEqual(records['queue_counts'], {'queued': 1})
        self.assertEqual(records['queue_eligibility']['eligible_total'], 1)
        row = self.job_record(records, self.queued)
        self.assertEqual(row['status'], 'queued')
        self.assertEqual(row['attempts'], 0)
        self.assertEqual(row['input_revision'], 4)
        self.assertEqual(row['draft_revision'], 4)
        self.assertTrue(row['draft_is_open'])
        self.assertFalse(row['owner_has_live_job'])
        self.assertFalse(row['owner_budget_blocks_claim'])
        self.assertEqual(row['organization_live_jobs'], 0)

    def test_owner_active_lease_budget_and_future_availability_are_distinguished(self):
        now = timezone.now()
        self.new_job(status='processing', attempts=3,
            attempt_history=[now.timestamp()] * 3, lease_until=now + timedelta(seconds=180))
        future = self.new_job(status='queued', attempts=0, available_at=now + timedelta(minutes=5))
        records, _ = self.diagnose()
        self.assertEqual(records['queue_counts'], {'processing': 1, 'queued': 2})
        self.assertEqual(records['queue_eligibility']['eligible_total'], 1)
        self.assertEqual(records['queue_eligibility']['queued_available_future'], 1)
        self.assertEqual(records['queue_eligibility']['processing_active_lease'], 1)
        row = self.job_record(records, self.queued)
        self.assertTrue(row['owner_has_live_job'])
        self.assertTrue(row['owner_budget_blocks_claim'])
        self.assertEqual(row['owner_hourly_attempts'], 3)
        self.assertEqual(row['organization_live_jobs'], 1)
        self.assertGreater(self.job_record(records, future)['available_in_seconds'], 0)

    def test_expired_and_missing_leases_remain_visible_without_recovery_writes(self):
        now = timezone.now()
        expired = self.new_job(status='processing', attempts=1,
            attempt_history=[now.timestamp()], lease_until=now - timedelta(seconds=10))
        missing = self.new_job(status='processing', attempts=1,
            attempt_history=[now.timestamp()], lease_until=None)
        records, _ = self.diagnose()
        self.assertEqual(records['queue_eligibility']['eligible_total'], 2)
        self.assertEqual(records['queue_eligibility']['processing_active_lease'], 0)
        self.assertEqual(records['queue_eligibility']['processing_expired_lease'], 1)
        self.assertEqual(records['queue_eligibility']['processing_missing_lease'], 1)
        self.assertLess(self.job_record(records, expired)['lease_remaining_seconds'], 0)
        self.assertIsNone(self.job_record(records, missing)['lease_remaining_seconds'])

    def test_arbitrary_error_text_is_hidden_while_fixed_provider_codes_are_reported(self):
        private_text = 'synthetic-private-diagnostic-sentinel'
        self.queued.sanitized_error = private_text
        self.queued.save(update_fields=['sanitized_error'])
        known = self.new_job(status='failed', attempts=1, sanitized_error='provider_http_401')
        records, raw = self.diagnose()
        self.assertNotIn(private_text, raw)
        self.assertEqual(self.job_record(records, self.queued)['error'], 'other_hidden')
        self.assertEqual(self.job_record(records, known)['error'], 'provider_http_401')
