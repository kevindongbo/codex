#!/usr/bin/env bash
# Read-only diagnostics for the already deployed scheduling queue.
# No service changes, task claiming, API calls or environment disclosure.
set -Eeuo pipefail
set +x
umask 077
readonly app=/opt/dongbo/app
readonly python=/opt/dongbo/venv/bin/python
readonly worker=dongbo-timetable-worker.service
readonly web=dongbo-erp.service
fail() { printf 'DIAGNOSTIC_STOP code=%s\n' "$1" >&2; exit "${2:-1}"; }
[[ "$EUID" == 0 ]] || fail root_required 2
[[ -d "$app/.git" && -f "$app/.env" && -x "$python" ]] || fail expected_runtime_missing 3
for command in git systemctl runuser journalctl timeout; do
  command -v "$command" >/dev/null 2>&1 || fail required_command_missing 3
done
cd "$app"
head_sha=$(git rev-parse HEAD 2>/dev/null) || fail git_head_unavailable 4
[[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || fail git_head_invalid 4
printf 'HEAD=%s\n' "$head_sha"
for unit in "$web" "$worker"; do
  for property in ActiveState SubState NRestarts ExecMainStatus ExecMainStartTimestamp; do
    value=$(systemctl show "$unit" -p "$property" --value 2>/dev/null) || fail service_metadata_unavailable 5
    printf '%s %s=%s\n' "$unit" "$property" "$value"
  done
done
exec_spec=$(systemctl show "$worker" -p ExecStart --value 2>/dev/null) || fail worker_command_unavailable 5
case "$exec_spec" in *run_timetable_worker*) printf 'worker_command_contains_consumer=true\n' ;; *) printf 'worker_command_contains_consumer=false\n' ;; esac
unset exec_spec
service_user=$(systemctl show "$worker" -p User --value 2>/dev/null) || fail worker_account_unavailable 5
[[ -n "$service_user" && "$service_user" != root && "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]] || fail unexpected_worker_account 5
web_user=$(systemctl show "$web" -p User --value 2>/dev/null) || fail web_account_unavailable 5
if [[ "$web_user" == "$service_user" ]]; then printf 'web_worker_account_match=true\n'; else printf 'web_worker_account_match=false\n'; fi
for unit in "$web" "$worker"; do
  files=$(systemctl show "$unit" -p EnvironmentFiles --value 2>/dev/null) || fail service_environment_metadata_unavailable 5
  if [[ "$files" == *"$app/.env"* ]]; then printf '%s uses_expected_app_environment=true\n' "$unit"; else printf '%s uses_expected_app_environment=false\n' "$unit"; fi
  if [[ -f /etc/dongbo/scheduling.env ]]; then
    if [[ "$files" == *'/etc/dongbo/scheduling.env'* ]]; then printf '%s uses_expected_scheduling_environment=true\n' "$unit"; else printf '%s uses_expected_scheduling_environment=false\n' "$unit"; fi
  fi
done
unset files
set +u
set -a
source "$app/.env" >/dev/null 2>&1 || fail app_environment_load_failed 6
if [[ -f /etc/dongbo/scheduling.env ]]; then source /etc/dongbo/scheduling.env >/dev/null 2>&1 || fail scheduling_environment_load_failed 6; fi
set +a
set -u
printf 'DIAGNOSTIC_CONTEXT=worker_os_account_with_expected_environment_files\n'
diagnostic_status=0
if timeout 45s runuser --preserve-environment -u "$service_user" -- "$python" backend/manage.py shell 2>/dev/null <<'QUEUE_PY'
import json
import re
from datetime import timedelta
from django.conf import settings
from django.db import connection, DatabaseError
from django.db.models import Count, Q
from django.utils import timezone
from apps.erp.models import AIInvocationLog, AIProviderConfig, Organization
from apps.erp.scheduling_models import ScheduleTerm, TimetableEvidence, TimetableImport, TimetableRecognitionJob

def emit(label, payload):
    print(label + '=' + json.dumps(payload, ensure_ascii=True, sort_keys=True))

safe_errors = {
    '', 'stale_draft', 'attempts_exhausted', 'provider_unavailable',
    'invalid_provider_endpoint', 'evidence_unavailable', 'image_too_large',
    'invalid_provider_parameters', 'unsupported_provider_parameters',
    'invalid_output', 'invalid_period', 'invalid_time', 'time_outside_template',
    'response_too_large', 'provider_timeout_or_network', 'recognition_internal_error',
}
safe_statuses = {'queued', 'processing', 'succeeded', 'failed'}
def safe_error(value):
    if value in safe_errors or isinstance(value, str) and re.fullmatch(r'provider_http_[0-9]{3}', value):
        return value
    return 'other_hidden'

def inspect_privileges():
    privileges = []
    with connection.cursor() as cursor:
        for model, needed in (
            (Organization, ('SELECT', 'UPDATE')),
            (TimetableRecognitionJob, ('SELECT', 'UPDATE')),
            (TimetableImport, ('SELECT', 'UPDATE')),
            (ScheduleTerm, ('SELECT',)), (TimetableEvidence, ('SELECT',)),
            (AIProviderConfig, ('SELECT',)), (AIInvocationLog, ('INSERT',)),
        ):
            for privilege in needed:
                cursor.execute('SELECT has_table_privilege(current_user, %s, %s)', [model._meta.db_table, privilege])
                privileges.append({'table': model._meta.db_table, 'privilege': privilege, 'allowed': cursor.fetchone()[0] is True})
    emit('worker_database_privileges', privileges)

try:
    now = timezone.now()
    since = now - timedelta(hours=1)
    limit = getattr(settings, 'SCHEDULING_RECOGNITION_HOURLY_LIMIT', 60)
    emit('runtime', {'scheduling_enabled': bool(settings.SCHEDULING_ENABLED), 'postgresql': connection.vendor == 'postgresql', 'hourly_limit': limit if type(limit) is int else 'invalid'})
    if connection.vendor == 'postgresql':
        inspect_privileges()
    jobs = TimetableRecognitionJob.objects.all()
    eligible = Q(status='queued') & (Q(available_at__isnull=True) | Q(available_at__lte=now)) | Q(status='processing', lease_until__lte=now)
    counts = {}
    for row in jobs.values('status').annotate(total=Count('pk')):
        status = row['status'] if row['status'] in safe_statuses else 'other_hidden'
        counts[status] = counts.get(status, 0) + row['total']
    emit('queue_counts', counts)
    emit('queue_eligibility', {
        'eligible_total': jobs.filter(eligible).count(),
        'queued_available_future': jobs.filter(status='queued', available_at__gt=now).count(),
        'processing_active_lease': jobs.filter(status='processing', lease_until__gt=now).count(),
        'processing_expired_lease': jobs.filter(status='processing', lease_until__lte=now).count(),
        'processing_missing_lease': jobs.filter(status='processing', lease_until__isnull=True).count(),
    })
    recent = jobs.order_by('-created_at').values(
        'id', 'timetable_import_id', 'organization_id', 'status', 'attempts',
        'input_revision', 'created_at', 'available_at', 'lease_until', 'heartbeat_at', 'sanitized_error',
        'timetable_import__revision', 'timetable_import__state', 'timetable_import__owner_id',
    )[:10]
    metadata = []
    for row in recent:
        owner_jobs = jobs.filter(organization_id=row['organization_id'], timetable_import__owner_id=row['timetable_import__owner_id'])
        histories = owner_jobs.filter(updated_at__gte=since).values_list('attempt_history', flat=True)
        attempts_used = sum(1 for history in histories if isinstance(history, list) for stamp in history if type(stamp) in (int, float) and stamp >= since.timestamp())
        live = jobs.filter(organization_id=row['organization_id'], status='processing', lease_until__gt=now)
        metadata.append({
            'job_id': str(row['id']), 'import_id': str(row['timetable_import_id']),
            'status': row['status'] if row['status'] in safe_statuses else 'other_hidden',
            'attempts': row['attempts'], 'input_revision': row['input_revision'],
            'draft_revision': row['timetable_import__revision'],
            'draft_is_open': row['timetable_import__state'] == 'draft',
            'age_seconds': round((now - row['created_at']).total_seconds()),
            'available_in_seconds': None if row['available_at'] is None else round((row['available_at'] - now).total_seconds()),
            'lease_remaining_seconds': None if row['lease_until'] is None else round((row['lease_until'] - now).total_seconds()),
            'heartbeat_age_seconds': None if row['heartbeat_at'] is None else round((now - row['heartbeat_at']).total_seconds()),
            'error': safe_error(row['sanitized_error']),
            'owner_hourly_jobs': owner_jobs.filter(created_at__gte=since).count(),
            'owner_hourly_attempts': attempts_used,
            'owner_budget_blocks_claim': type(limit) is int and attempts_used >= max(1, limit),
            'organization_live_jobs': live.count(),
            'owner_has_live_job': live.filter(timetable_import__owner_id=row['timetable_import__owner_id']).exists(),
        })
    emit('recent_jobs', metadata)
    if connection.vendor == 'postgresql':
        try:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT pid, wait_event_type, wait_event, pg_blocking_pids(pid)
                    FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user
                    AND pid<>pg_backend_pid() AND cardinality(pg_blocking_pids(pid))>0 ORDER BY pid LIMIT 10''')
                blocked = [{'pid': pid, 'wait_event_type': kind, 'wait_event': event, 'blocking_pids': pids} for pid, kind, event, pids in cursor.fetchall()]
            emit('visible_same_database_user_blocked_connections', blocked)
        except DatabaseError:
            emit('blocking_diagnostic', {'available': False})
except Exception as exc:
    # Only fixed class names are emitted. Never print exception text/tracebacks.
    known = {'ProgrammingError', 'OperationalError', 'InterfaceError', 'PermissionError', 'ImproperlyConfigured', 'TypeError', 'ValueError'}
    emit('queue_diagnostic_failed', {'type': type(exc).__name__ if type(exc).__name__ in known else 'other_hidden'})
    raise SystemExit(7)
QUEUE_PY
then :; else
  printf 'DIAGNOSTIC_PARTIAL code=queue_inspection_failed\n' >&2
  diagnostic_status=7
fi
journal_summary_code=$(cat <<'JOURNAL_PY'
import json
import re
import sys
text = sys.stdin.read()
types = ('ProgrammingError', 'OperationalError', 'InterfaceError', 'PermissionError',
         'FileNotFoundError', 'ImproperlyConfigured', 'CommandError', 'NotSupportedError',
         'IntegrityError', 'TypeError', 'ValueError', 'InvalidToken', 'ModuleNotFoundError', 'ImportError')
counts = {name: len(re.findall(r'\b' + name + r'\b', text)) for name in types}
patterns = {
    'permission_denied': r'permission denied',
    'nullable_join_lock': r'FOR UPDATE cannot be applied to the nullable side',
    'database_auth_failed': r'password authentication failed|Peer authentication failed',
    'database_connection_closed': r'connection already closed|server closed the connection',
    'read_only_filesystem': r'read.only file system',
    'scheduling_disabled': r'SCHEDULING_ENABLED is disabled',
    'worker_exit': r'Main process exited|Failed with result',
    'worker_restart': r'Scheduled restart job|restart counter',
}
counts.update({name: sum(bool(re.search(pattern, line, re.IGNORECASE)) for line in text.splitlines()) for name, pattern in patterns.items()})
print('journal_known_event_counts=' + json.dumps(counts, sort_keys=True))
JOURNAL_PY
)
if journalctl -u "$worker" --since '-30 min' -n 400 -o cat --no-pager 2>/dev/null | "$python" -c "$journal_summary_code" 2>/dev/null; then :; else
  printf 'JOURNAL_SUMMARY=unavailable\n'
  [[ "$diagnostic_status" != 0 ]] || diagnostic_status=8
fi
printf 'READ_ONLY_DIAGNOSTIC_COMPLETE status=%s; no tasks claimed, API calls, service changes or data writes.\n' "$diagnostic_status"
exit "$diagnostic_status"
