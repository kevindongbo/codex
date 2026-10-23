"""Bounded live-probe behavior, with no database or provider access."""
import copy
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from apps.erp.management.commands import verify_timetable_recognition as verification
from apps.erp.timetable_recognition import RecognitionError


@override_settings(SCHEDULING_ENABLED=True)
class RecognitionVerificationTests(SimpleTestCase):
    def setUp(self):
        self.original_grid = [[{'status': 'unknown', 'course_name': ''} for _ in range(12)] for _ in range(7)]
        self.provider = SimpleNamespace(enabled=True, organization_id=1)
        self.imp = MagicMock(state='draft', organization_id=1, revision=7,
            term=SimpleNamespace(recognition_provider=self.provider), draft_grid=copy.deepcopy(self.original_grid))
        self.job = MagicMock(pk=None)
        query = MagicMock()
        query.get.return_value = self.imp
        read_import = patch.object(verification.TimetableImport.objects, 'select_related', return_value=query)
        self.read_import = read_import.start()
        self.addCleanup(read_import.stop)
        constructor = patch.object(verification, 'TimetableRecognitionJob', return_value=self.job)
        self.constructor = constructor.start()
        self.addCleanup(constructor.stop)
        vision = patch.object(verification, 'invoke_vision')
        self.vision = vision.start()
        self.addCleanup(vision.stop)

    def run_probe(self, attempts=3):
        output = io.StringIO()
        call_command('verify_timetable_recognition', '--import-id', 'draft-id',
            '--attempts', str(attempts), stdout=output)
        return output.getvalue()

    def assert_unchanged(self):
        self.assertEqual(self.imp.revision, 7)
        self.assertEqual(self.imp.state, 'draft')
        self.assertEqual(self.imp.draft_grid, self.original_grid)
        self.assertIsNone(self.job.pk)
        self.imp.save.assert_not_called()
        self.job.save.assert_not_called()
        self.constructor.objects.create.assert_not_called()
        self.constructor.assert_called_once_with(organization_id=1,
            timetable_import=self.imp, provider=self.provider, input_revision=7)

    def test_malformed_model_outputs_retry_then_succeed_without_saving(self):
        for code in ('invalid_output', 'invalid_time', 'invalid_period', 'time_outside_template'):
            with self.subTest(code=code):
                self.constructor.reset_mock()
                self.vision.reset_mock()
                grid = copy.deepcopy(self.original_grid)
                grid[1][2] = {'status': 'class', 'course_name': '课程'}
                self.vision.side_effect = [RecognitionError(code), grid]
                output = self.run_probe()
                self.assertEqual(self.vision.call_count, 2)
                self.assertIn(f'attempt=1 status={code}', output)
                self.assertIn('attempt=2 occupied_cells=1 unknown_cells=83', output)
                self.assert_unchanged()

    def test_authentication_and_missing_endpoint_errors_stop_after_one_call(self):
        for code in ('provider_http_401', 'provider_http_403', 'provider_http_404'):
            with self.subTest(code=code):
                self.constructor.reset_mock()
                self.vision.reset_mock()
                self.vision.side_effect = RecognitionError(code)
                with self.assertRaisesMessage(CommandError, code):
                    self.run_probe(attempts=5)
                self.assertEqual(self.vision.call_count, 1)
                self.assert_unchanged()

    def test_invalid_provider_configuration_does_not_spend_further_attempts(self):
        for code in ('invalid_provider_parameters', 'unsupported_provider_parameters',
                'invalid_provider_endpoint', 'provider_unavailable'):
            with self.subTest(code=code):
                self.constructor.reset_mock()
                self.vision.reset_mock()
                self.vision.side_effect = RecognitionError(code)
                with self.assertRaisesMessage(CommandError, code):
                    self.run_probe(attempts=5)
                self.assertEqual(self.vision.call_count, 1)
                self.assert_unchanged()

    def test_empty_candidates_exhaust_only_the_explicit_attempt_budget(self):
        self.vision.return_value = copy.deepcopy(self.original_grid)
        with self.assertRaisesMessage(CommandError, 'no_courses'):
            self.run_probe(attempts=5)
        self.assertEqual(self.vision.call_count, 5)
        self.assert_unchanged()

    def test_empty_result_after_format_error_reports_the_latest_failure(self):
        self.vision.side_effect = [RecognitionError('invalid_output'), copy.deepcopy(self.original_grid)]
        with self.assertRaisesMessage(CommandError, 'no_courses'):
            self.run_probe(attempts=2)
        self.assertEqual(self.vision.call_count, 2)
        self.assert_unchanged()
