#!/usr/bin/env bash
# Execute a copy outside the checkout. No migration/dependency/config changes.
set -Eeuo pipefail
set +x
umask 077
readonly app=/opt/dongbo/app
readonly python=/opt/dongbo/venv/bin/python
readonly branch=codex/fix-recognition-store-profit-20261017
readonly service=dongbo-erp.service
readonly worker=dongbo-timetable-worker.service
readonly domain=dongbokeji.com
readonly target=${1:-}
old=''; backup=''; changed=0
fail() { printf '%s\n' "$*" >&2; exit 1; }
runtime_command() { (umask 022; "$@"); }
health() {
  local attempt
  for attempt in {1..30}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health/ 2>/dev/null |
      "$python" -c 'import json,sys; x=json.load(sys.stdin); sys.exit(not(x.get("status")=="ok" and x.get("database")=="ok"))' 2>/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}
verify_assets() {
  local asset path expected actual
  for asset in index.html app.js team.js styles.css profit-calculator.js scheduling.js scheduling.css; do
    path=$asset; [[ "$asset" != index.html ]] || path=''
    expected=$(sha256sum "$app/$asset"); expected=${expected%% *}
    actual=$(curl -fsS --max-time 20 --compressed --resolve "$domain:443:127.0.0.1" \
      -H 'Cache-Control: no-cache' "https://$domain/$path?release=$1" | sha256sum) || return 1
    [[ "${actual%% *}" == "$expected" ]] || return 1
  done
}
readable() {
  local path
  while IFS= read -r -d '' path; do runuser -u "$service_user" -- test -r "$app/$path" || return 1; done < <(git -C "$app" ls-files -z -- backend '*.js' '*.css' '*.html')
  runuser -u "$service_user" -- test -r "$app/dist/server/index.js"
}
rollback() {
  local status=$? ok=1
  trap - ERR
  set +e
  printf 'Release failed (%s). Backup: %s\n' "$status" "$backup" >&2
  if [[ "$changed" == 1 ]]; then
    runtime_command git -C "$app" switch --detach "$old" || ok=0
    (cd "$app" && runtime_command node scripts/build-site.mjs) || ok=0
    readable || ok=0
    systemctl restart "$service" "$worker" || ok=0
    systemctl is-active --quiet "$service" || ok=0
    systemctl is-active --quiet "$worker" || ok=0
    health && verify_assets "$old" || ok=0
    if [[ "$ok" == 1 ]]; then printf 'CODE ROLLBACK VERIFIED: %s\n' "$old"; else printf 'ROLLBACK NOT VERIFIED; inspect services.\n' >&2; fi
  fi
  printf 'Database, originals and configuration retained; no database restore or reverse migration.\n'
  exit "$status"
}
[[ "$EUID" == 0 ]] || fail 'Run as root.'
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || fail 'Pass the reviewed full SHA.'
[[ -d "$app/.git" && -x "$python" && -f "$app/.env" ]] || fail 'Expected paths missing.'
for command in git node curl sha256sum nginx systemctl flock runuser pg_dump pg_restore; do command -v "$command" >/dev/null || fail "Missing command: $command"; done
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || fail 'Another release is running.'
cd "$app"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'Tracked edits exist; preserve before release.'
[[ -z "$(git ls-files .env backend/.env)" ]] || fail 'Environment unexpectedly tracked.'
case "$(git remote get-url origin)" in
  https://github.com/kevindongbo/codex.git|https://github.com/kevindongbo/codex|git@github.com:kevindongbo/codex.git) ;;
  *) fail 'Unexpected origin.' ;;
esac
git fetch origin "$branch"
[[ "$(git rev-parse FETCH_HEAD)" == "$target" ]] || fail 'Remote SHA differs; no checkout performed.'
old=$(git rev-parse HEAD)
git merge-base --is-ancestor "$old" "$target" || fail 'Divergent or newer server code; no overwrite.'
[[ -z "$(git diff --name-only "$old" "$target" -- backend/apps/erp/migrations backend/requirements.txt)" ]] || fail 'Schema/dependency changes require separate release.'
service_user=$(systemctl show "$service" -p User --value)
[[ -n "$service_user" && "$service_user" != root && "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Expected non-root service account.'
[[ "$(systemctl show "$service" -p WorkingDirectory --value)" == "$app/backend" ]] || fail 'Unexpected working directory.'
[[ "$(systemctl show "$worker" -p WorkingDirectory --value)" == "$app/backend" ]] || fail 'Unexpected worker working directory.'
[[ "$(systemctl show "$service" -p EnvironmentFiles --value)" == *"$app/.env"* ]] || fail 'Unexpected web environment configuration.'
[[ "$(systemctl show "$worker" -p EnvironmentFiles --value)" == *"$app/.env"* ]] || fail 'Unexpected worker environment configuration.'
if [[ -f /etc/dongbo/scheduling.env ]]; then
  [[ "$(systemctl show "$service" -p EnvironmentFiles --value)" == *'/etc/dongbo/scheduling.env'* ]] || fail 'Web scheduling configuration differs.'
  [[ "$(systemctl show "$worker" -p EnvironmentFiles --value)" == *'/etc/dongbo/scheduling.env'* ]] || fail 'Worker scheduling configuration differs.'
fi
systemctl is-active --quiet "$service"
systemctl is-active --quiet "$worker"
nginx -t
health
verify_assets "$old"
set +u
set -a
source "$app/.env" >/dev/null 2>&1
[[ ! -f /etc/dongbo/scheduling.env ]] || source /etc/dongbo/scheduling.env >/dev/null 2>&1
set +a
set -u
"$python" backend/manage.py check
"$python" backend/manage.py migrate --check
"$python" backend/manage.py shell -c 'from django.db import connection; d=connection.settings_dict; assert connection.vendor=="postgresql" and d["NAME"]=="dongbo_erp" and d.get("HOST", "") in ("", "localhost", "127.0.0.1", "/var/run/postgresql") and str(d.get("PORT") or "5432")=="5432", "Unexpected database location"'
install -d -m 700 /opt/dongbo/backups
backup=$(mktemp -d /opt/dongbo/backups/recognition-store-profit-XXXXXXXX)
printf '%s\n' "$old" > "$backup/previous-sha.txt"
git archive "$old" > "$backup/previous-code.tar"
trap rollback ERR
changed=1
systemctl stop "$worker" "$service"
runuser -u postgres -- pg_dump --dbname=dongbo_erp --format=custom > "$backup/dongbo_erp.dump"
pg_restore --list "$backup/dongbo_erp.dump" >/dev/null
runtime_command git switch --detach "$target"
runtime_command node scripts/build-site.mjs
readable
"$python" backend/manage.py check
"$python" backend/manage.py check_scheduling_release --expect-migrated
"$python" backend/manage.py check_recognition_store_release
systemctl restart "$service" "$worker"
health
systemctl is-active --quiet "$service"
systemctl is-active --quiet "$worker"
verify_assets "$target"
trap - ERR
printf 'REPAIR CODE / SERVICES / ASSETS VERIFIED AT LOCAL NGINX ORIGIN\nSHA: %s\nBackup: %s\n' "$target" "$backup"
printf 'No migrations, dependency installs or configuration changes. Live vision and signed-in public workflows still require acceptance.\n'
