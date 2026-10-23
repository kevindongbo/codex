import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import test from 'node:test';

const script = readFileSync(new URL('../deploy/diagnose-timetable-queue.sh', import.meta.url), 'utf8').replaceAll('\r\n', '\n');
const bash = process.env.BASH_EXECUTABLE || 'bash';
const bundledPython = resolve(dirname(process.execPath), '../../python/python.exe');
const python = process.env.PYTHON_EXECUTABLE || (existsSync(bundledPython) ? bundledPython : 'python3');

test('queue diagnostic parses and retains only read-only, non-API commands', () => {
  const result = spawnSync(bash, ['-n'], {input: script, encoding: 'utf8'});
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.match(script, /runuser --preserve-environment -u "\$service_user" -- "\$python" backend\/manage.py shell 2>\/dev\/null/);
  assert.match(script, /source "\$app\/\.env" >\/dev\/null 2>&1/);
  assert.doesNotMatch(script, /systemctl (?:start|stop|restart|enable|disable)|claim_job\(|run_one_job\(|invoke_vision\(|verify_timetable_recognition|\.save\(|(?:objects|jobs)\.update\(|\.create\(|\.delete\(|pg_dump|pg_restore|git (?:fetch|switch|reset|pull)|GRANT|ALTER TABLE/);
  assert.match(script, /\[:10\]/);
  assert.match(script, /safe_error\(row\['sanitized_error'\]\)/);
  assert.match(script, /usename=current_user/);
  assert.match(script, /datname=current_database\(\)/);
  assert.doesNotMatch(script, /SELECT[^\n]*\bquery\b|print\([^\n]*(?:exec_spec|files|service_user|SECRET|api_key|course_name|draft_grid|evidence\.private_file)/i);
});

test('journal diagnostic counts known error categories without revealing log contents', () => {
  const code = script.match(/<<'JOURNAL_PY'\n([\s\S]*?)\nJOURNAL_PY/)[1];
  const secret = 'private-log-value-do-not-print-582951';
  const log = `ProgrammingError: permission denied for table anything\nOperationalError: database ${secret}\nFOR UPDATE cannot be applied to the nullable side of an outer join\nMain process exited, code=exited\nScheduled restart job, restart counter is at 9\nAPI_KEY=${secret}\n`;
  const result = spawnSync(python, ['-c', code], {input: log, encoding: 'utf8'});
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.doesNotMatch(result.stdout, new RegExp(secret));
  const counts = JSON.parse(result.stdout.trim().split('=', 2)[1]);
  assert.equal(counts.ProgrammingError, 1);
  assert.equal(counts.OperationalError, 1);
  assert.equal(counts.permission_denied, 1);
  assert.equal(counts.nullable_join_lock, 1);
  assert.equal(counts.worker_exit, 1);
  assert.equal(counts.worker_restart, 1);
  assert.ok(Object.values(counts).every(value => Number.isInteger(value) && value >= 0));
});

test('queue diagnostic error field permits fixed codes and hides arbitrary exception text', () => {
  const body = script.match(/<<'QUEUE_PY'\n([\s\S]*?)\nQUEUE_PY/)[1];
  const helpers = body.slice(body.indexOf('safe_errors ='), body.indexOf('\ntry:\n'));
  const checks = '\nassert safe_error("provider_http_401") == "provider_http_401"\nassert safe_error("provider_timeout_or_network") == "provider_timeout_or_network"\nassert safe_error("API_KEY=private-value") == "other_hidden"\n';
  const result = spawnSync(python, ['-c', 'import re\n' + helpers + checks], {encoding: 'utf8'});
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
});
