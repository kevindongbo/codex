"""No network or paid model required: exercise vision transport and queue invariants."""
import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from PIL import Image
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from apps.erp.models import Organization, AIProviderConfig, AIInvocationLog
from apps.erp.scheduling_models import ScheduleTerm, TimetableEvidence, TimetableImport, TimetableRecognitionJob, default_periods
from apps.erp.timetable_recognition import candidate_grid, enqueue_recognition, claim_job, finish_job, heartbeat, invoke_vision, run_one_job, RecognitionError


class RecognitionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Schedule', slug='recognition-tests')
        self.user = get_user_model().objects.create_user(username='recognition-user')
        self.provider = AIProviderConfig.objects.create(organization=self.org, name='Vision', api_base_url='https://vision.example/v1', model_name='vision-test', api_key_encrypted='test-encrypted')
        self.term = ScheduleTerm.objects.create(organization=self.org, name='Term', first_monday=date(2026, 9, 21), recognition_provider=self.provider)
        self.evidence = TimetableEvidence.objects.create(organization=self.org, owner=self.user, uploaded_by=self.user, private_file='test.png', sha256='a' * 64, original_name='test.png', content_type='image/png', size=100, pixel_width=10, pixel_height=10)
        self.imp = self.new_import()

    def new_import(self, owner=None):
        return TimetableImport.objects.create(organization=self.org, owner=owner or self.user, term=self.term, evidence=self.evidence, selected_weeks=[1], draft_grid=[])

    def test_candidates_never_mark_unseen_weekends_or_empty_cells_free(self):
        grid = candidate_grid({'courses': [{'day': 1, 'start_period': 1, 'end_period': 2, 'course_name': '课程'}], 'warnings': ['Missing weekend']}, default_periods())
        self.assertEqual(grid[0][0]['status'], 'class')
        self.assertEqual(grid[0][1]['status'], 'class')
        self.assertEqual(grid[0][2]['status'], 'unknown')
        self.assertTrue(all(c['status'] == 'unknown' for row in grid[5:] for c in row))

    def test_clock_boundaries_and_schema_whitelist(self):
        grid = candidate_grid({'courses': [{'day': 2, 'start_time': '09:05', 'end_time': '09:15'}]}, default_periods()) if False else None
        with self.assertRaises(RecognitionError):
            candidate_grid({'courses': [{'day': 2, 'start_time': '09:05', 'end_time': '09:15'}]}, default_periods())
        grid = candidate_grid({'courses': [{'day': 2, 'start_time': '09:05', 'end_time': '10:00'}]}, default_periods())
        self.assertEqual(grid[1][0]['status'], 'unknown')
        self.assertEqual(grid[1][1]['status'], 'class')
        for invalid in ({'courses': [], 'execute': 'delete'}, {'courses': [{'day': True, 'start_period': 1, 'end_period': 2}]}, {'courses': [{'day': 1, 'start_period': 0, 'end_period': 13}]}):
            with self.assertRaises(RecognitionError):
                candidate_grid(invalid, default_periods())

    def test_unconfigured_model_manual_workflow_remains_available(self):
        self.term.recognition_provider = None
        self.term.save()
        with self.assertRaisesMessage(ValidationError, '自动识别未配置'):
            enqueue_recognition(self.imp, self.user)
        self.assertFalse(TimetableRecognitionJob.objects.exists())

    def test_enqueue_idempotent_and_rate_limited(self):
        first = enqueue_recognition(self.imp, self.user)
        self.assertEqual(first.pk, enqueue_recognition(self.imp, self.user).pk)
        for _ in range(9):
            enqueue_recognition(self.new_import(), self.user)
        with self.assertRaises(Throttled):
            enqueue_recognition(self.new_import(), self.user)

    def test_claim_limits_owner_and_organization_concurrency(self):
        enqueue_recognition(self.imp, self.user)
        enqueue_recognition(self.new_import(), self.user)
        self.assertIsNotNone(claim_job())
        self.assertIsNone(claim_job())
        second = get_user_model().objects.create_user(username='second-recognition')
        enqueue_recognition(self.new_import(second), second)
        self.assertIsNotNone(claim_job())
        third = get_user_model().objects.create_user(username='third-recognition')
        enqueue_recognition(self.new_import(third), third)
        self.assertIsNone(claim_job())

    def test_expired_lease_reclaimed_old_result_rejected(self):
        enqueue_recognition(self.imp, self.user)
        old = claim_job()
        TimetableRecognitionJob.objects.filter(pk=old.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(heartbeat(old.pk, old.lease_token), 0)
        new = claim_job()
        self.assertNotEqual(new.lease_token, old.lease_token)
        self.assertFalse(finish_job(old, grid=[]))
        grid = candidate_grid({'courses': []}, default_periods())
        self.assertTrue(finish_job(new, grid=grid))
        self.imp.refresh_from_db()
        self.assertEqual(self.imp.state, 'draft')
        self.assertEqual(self.imp.revision, 2)

    def test_edit_during_vision_does_not_overwrite_manual_grid(self):
        enqueue_recognition(self.imp, self.user)
        job = claim_job()
        TimetableImport.objects.filter(pk=self.imp.pk).update(revision=2, draft_grid=[{'manual': True}])
        finish_job(job, grid=[])
        self.imp.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(self.imp.draft_grid, [{'manual': True}])
        self.assertEqual(job.sanitized_error, 'stale_draft')

    def test_transient_retries_backoff_and_three_attempt_cap(self):
        enqueue_recognition(self.imp, self.user)
        for index in range(3):
            job = claim_job()
            self.assertEqual(job.attempts, index + 1)
            finish_job(job, error=RecognitionError('provider_http_429', True))
            job.refresh_from_db()
            if index < 2:
                self.assertEqual(job.status, 'queued')
                self.assertIsNone(claim_job())
                TimetableRecognitionJob.objects.filter(pk=job.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(claim_job())

    def test_retry_attempts_count_towards_hourly_budget(self):
        enqueue_recognition(self.imp, self.user)
        job = claim_job()
        finish_job(job, error=RecognitionError('network', True))
        TimetableRecognitionJob.objects.filter(pk=job.pk).update(available_at=timezone.now(), attempt_history=[timezone.now().timestamp()] * 10)
        self.assertIsNone(claim_job())

    def test_mock_transport_vision_original_preserved_and_logs_sanitized(self):
        enqueue_recognition(self.imp, self.user)
        job = claim_job()
        with tempfile.TemporaryDirectory() as folder, self.settings(SCHEDULING_PRIVATE_ROOT=folder):
            original = io.BytesIO()
            Image.new('RGB', (10, 10)).save(original, format='PNG')
            path = Path(folder) / 'test.png'
            path.write_bytes(original.getvalue())
            mock = MagicMock()
            mock.open.return_value.__enter__.return_value.read.return_value = json.dumps({'choices': [{'message': {'content': json.dumps({'courses': [], 'warnings': ['check missing weekends']})}}]}).encode()
            with patch('apps.erp.timetable_recognition.build_opener', return_value=mock), patch('apps.erp.timetable_recognition.decrypt_secret', return_value='do-not-log'):
                result = invoke_vision(job)
            body = json.loads(mock.open.call_args.args[0].data)
            self.assertIn('untrusted data', body['messages'][0]['content'])
            self.assertTrue(body['messages'][1]['content'][0]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(path.read_bytes(), original.getvalue())
            self.assertEqual(result[6][11]['status'], 'unknown')
            self.assertEqual(AIInvocationLog.objects.get().status, 'success')
            mock.open.side_effect = HTTPError('https://vision.example', 401, 'do-not-log', {}, None)
            with patch('apps.erp.timetable_recognition.build_opener', return_value=mock), patch('apps.erp.timetable_recognition.decrypt_secret', return_value='do-not-log'):
                with self.assertRaises(RecognitionError) as error:
                    invoke_vision(job)
            self.assertFalse(error.exception.retryable)
            self.assertEqual(AIInvocationLog.objects.filter(status='failed').get().error_message, 'provider_http_401')

    def test_worker_unexpected_error_redacted(self):
        enqueue_recognition(self.imp, self.user)
        with patch('apps.erp.timetable_recognition.invoke_vision', side_effect=RuntimeError('secret text')):
            self.assertTrue(run_one_job())
        job = self.imp.jobs.get()
        self.assertEqual(job.sanitized_error, 'recognition_internal_error')
        self.assertNotIn('secret', job.sanitized_error)
