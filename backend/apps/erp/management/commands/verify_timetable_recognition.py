"""Explicit live provider probe: private evidence stays private, no schedule writes."""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.exceptions import ValidationError
from apps.erp.scheduling_models import TimetableImport, TimetableRecognitionJob
from apps.erp.timetable_recognition import RecognitionError, invoke_vision


# Only this explicit, bounded probe repeats malformed model output. The worker's
# automatic retry policy and recognition budgets remain unchanged.
PROBE_RETRYABLE_OUTPUT_ERRORS = frozenset({
    'invalid_output', 'invalid_time', 'invalid_period', 'time_outside_template',
})


class Command(BaseCommand):
    help = '使用所选草稿的原图和已配置 API 做真实识别，只输出课程格数量；会产生供应商调用费用。'

    def add_arguments(self, parser):
        parser.add_argument('--import-id', required=True)
        parser.add_argument('--attempts', type=int, default=1, choices=range(1, 6))

    def handle(self, *args, **options):
        if not settings.SCHEDULING_ENABLED:
            raise CommandError('团队排班尚未启用')
        try:
            imp = TimetableImport.objects.select_related('term__recognition_provider', 'evidence').get(pk=options['import_id'])
        except (TimetableImport.DoesNotExist, ValueError, ValidationError):
            raise CommandError('指定草稿不存在或编号无效') from None
        if imp.state != 'draft':
            raise CommandError('请选择未确认草稿；不会修改任何已发布课表')
        provider = imp.term.recognition_provider
        if not provider or not provider.enabled or provider.organization_id != imp.organization_id:
            raise CommandError('学期未配置有效的同组织识别模型')
        # Unsaved job is deliberately used: probe cannot publish or replace a
        # draft; invoke_vision still appends a redacted provider invocation log.
        job = TimetableRecognitionJob(organization_id=imp.organization_id, timetable_import=imp, provider=provider, input_revision=imp.revision)
        last = 'no_courses'
        for attempt in range(1, options['attempts'] + 1):
            try:
                grid = invoke_vision(job)
                occupied = sum(cell['status'] == 'class' for day in grid for cell in day)
                last = 'no_courses'
                self.stdout.write(f'LIVE API attempt={attempt} occupied_cells={occupied} unknown_cells={84-occupied}')
                if occupied:
                    self.stdout.write(self.style.SUCCESS('真实 API 返回有效课程候选；未保存草稿或发布排班，识别准确率仍需本人校对。'))
                    return
            except RecognitionError as exc:
                last = exc.code
                self.stdout.write(f'LIVE API attempt={attempt} status={exc.code}')
                if not exc.retryable and exc.code not in PROBE_RETRYABLE_OUTPUT_ERRORS:
                    break
            except Exception:
                # Raw SDK/crypto/file exceptions can contain credentials/paths.
                raise CommandError('识别配置或原图不可用；请在服务器本地排查，勿输出密钥') from None
        raise CommandError(f'真实识别未取得有效课程候选：{last}；草稿和原图保留')
