"""Private source evidence and durable, versioned team schedules."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from .models import OrganizationScopedModel, AppendOnlyManager


def default_periods():
    return [dict(number=i + 1, start=a, end=b) for i, (a, b) in enumerate([
        ('08:20', '09:05'), ('09:15', '10:00'), ('10:20', '11:05'), ('11:15', '12:00'),
        ('14:00', '14:45'), ('14:55', '15:40'), ('16:00', '16:45'), ('16:55', '17:40'),
        ('18:40', '19:25'), ('19:35', '20:00'), ('20:20', '21:00'), ('21:00', '21:40')])]


class ScheduleTerm(OrganizationScopedModel):
    name = models.CharField(max_length=120)
    first_monday = models.DateField()
    week_count = models.PositiveSmallIntegerField(default=20)
    timezone = models.CharField(max_length=64, default='Asia/Shanghai')
    periods = models.JSONField(default=default_periods)
    locked_at = models.DateTimeField(null=True)
    recognition_provider = models.ForeignKey('AIProviderConfig', null=True, blank=True, on_delete=models.PROTECT)


class ScheduleParticipant(OrganizationScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    effective_from = models.DateField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'user'], name='sched_participant_unique')]


class TimetableEvidence(OrganizationScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    private_file = models.CharField(max_length=250)
    sha256 = models.CharField(max_length=64)
    original_name = models.CharField(max_length=250)
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    pixel_width = models.PositiveIntegerField()
    pixel_height = models.PositiveIntegerField()
    archived_at = models.DateTimeField(null=True)
    class Meta:
        indexes = [models.Index(fields=['organization', 'owner', 'created_at'], name='sched_evidence_owner')]
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('原始凭证不可改写')
        return super().save(*args, **kwargs)


class TimetableImport(OrganizationScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    term = models.ForeignKey(ScheduleTerm, on_delete=models.PROTECT)
    evidence = models.ForeignKey(TimetableEvidence, on_delete=models.PROTECT)
    state = models.CharField(max_length=16, default='draft')
    draft_grid = models.JSONField(default=list)
    selected_weeks = models.JSONField(default=list)
    weekend_day = models.CharField(max_length=3, default='sat')
    revision = models.PositiveIntegerField(default=1)
    confirmed_at = models.DateTimeField(null=True)


class TimetableRecognitionJob(OrganizationScopedModel):
    timetable_import = models.ForeignKey(TimetableImport, on_delete=models.PROTECT, related_name='jobs')
    input_revision = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default='queued')
    attempts = models.PositiveSmallIntegerField(default=0)
    attempt_history = models.JSONField(default=list)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)
    available_at = models.DateTimeField(null=True)
    provider = models.ForeignKey('AIProviderConfig', null=True, on_delete=models.PROTECT)
    sanitized_error = models.CharField(max_length=500, blank=True)
    candidate_grid = models.JSONField(default=list)
    recognition_warnings = models.JSONField(default=list)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['timetable_import', 'input_revision'], name='sched_job_revision_unique')]


class MemberWeekPlan(OrganizationScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    term = models.ForeignKey(ScheduleTerm, on_delete=models.PROTECT)
    week_index = models.PositiveSmallIntegerField()
    week_start = models.DateField()
    confirmed_grid = models.JSONField(default=list)
    weekend_day = models.CharField(max_length=3, default='sat')
    evidence = models.ForeignKey(TimetableEvidence, on_delete=models.PROTECT)
    source_import = models.ForeignKey(TimetableImport, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'owner', 'week_start'], name='sched_member_week_unique')]


class MemberWeekPlanVersion(OrganizationScopedModel):
    plan = models.ForeignKey(MemberWeekPlan, on_delete=models.PROTECT, related_name='versions')
    version = models.PositiveIntegerField()
    grid = models.JSONField()
    weekend_day = models.CharField(max_length=3)
    evidence = models.ForeignKey(TimetableEvidence, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    objects = AppendOnlyManager()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['plan', 'version'], name='sched_plan_version_unique')]
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('历史版本不可修改')
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError('历史版本不可删除')


class WorkScheduleCell(OrganizationScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    date = models.DateField()
    period = models.PositiveSmallIntegerField()
    base_status = models.CharField(max_length=12)
    effective_status = models.CharField(max_length=12)
    plan_version = models.ForeignKey(MemberWeekPlanVersion, null=True, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    period_start = models.TimeField()
    period_end = models.TimeField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'owner', 'date', 'period'], name='sched_cell_unique')]
        indexes = [models.Index(fields=['organization', 'date', 'effective_status'], name='sched_board_lookup')]


class ScheduleOverride(OrganizationScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    date = models.DateField()
    period = models.PositiveSmallIntegerField()
    authority = models.CharField(max_length=5)
    status = models.CharField(max_length=12)
    reason = models.CharField(max_length=500, blank=True)
    show_annotation = models.BooleanField(default=True)
    force = models.BooleanField(default=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    revoked_at = models.DateTimeField(null=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    revoke_reason = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'owner', 'date', 'period', 'authority'], condition=Q(revoked_at__isnull=True), name='sched_active_override_unique')]


class ScheduleMutation(OrganizationScopedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'actor', 'idempotency_key'], name='sched_mutation_unique')]
