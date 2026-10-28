#!/usr/bin/env bash
# Copy outside checkout before execution. PostgreSQL schema is additive.
set -Eeuo pipefail
set +x
umask 077
readonly app=/opt/dongbo/app
readonly python=/opt/dongbo/venv/bin/python
readonly branch=codex/implement-account-us-mx-camera-20261027
readonly service=dongbo-erp.service
readonly worker=dongbo-timetable-worker.service
readonly domain=dongbokeji.com
readonly target=${1:-}
readonly mode=${2:-}
readonly resume_backup=${3:-}
old=''; backup=''; stopped=0; changed=0; migration_started=0
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
  for asset in index.html app.js team.js styles.css profit-calculator.js market-profit.js scheduling.js scheduling.css; do
    # Old releases may not contain the new asset during preflight.
    [[ -f "$app/$asset" ]] || { [[ "$asset" == market-profit.js && "$1" == "$old" ]] && continue; return 1; }
    path=$asset; [[ "$asset" != index.html ]] || path=''
    expected=$(sha256sum "$app/$asset"); expected=${expected%% *}
    actual=$(curl -fsS --max-time 20 --compressed --resolve "$domain:443:127.0.0.1" -H 'Cache-Control: no-cache' "https://$domain/$path?release=$1" | sha256sum) || return 1
    [[ "${actual%% *}" == "$expected" ]] || return 1
  done
}
on_error() {
  local code=$?
  trap - ERR
  set +e
  printf 'RELEASE FAILED (%s). Backup: %s\n' "$code" "$backup" >&2
  if [[ "$migration_started" == 1 ]]; then
    systemctl stop "$service" "$worker"
    printf 'MAINTENANCE: new code/schema retained. Do not start the old authentication backend or reverse 0039. Fix forward and rerun this release. No database restore was performed.\n' >&2
  elif [[ "$stopped" == 1 ]]; then
    if [[ "$changed" == 1 ]]; then
      runtime_command git -C "$app" switch --detach "$old" && (cd "$app" && runtime_command node scripts/build-site.mjs)
    fi
    systemctl restart "$service" "$worker"
    if health && systemctl is-active --quiet "$service" && systemctl is-active --quiet "$worker" && verify_assets "$old"; then
      printf 'PRE-MIGRATION CODE/SERVICES RESTORED: %s\n' "$old"
    else printf 'RESTORATION NOT VERIFIED; inspect services.\n' >&2; fi
  fi
  exit "$code"
}
[[ "$EUID" == 0 ]] || fail 'Run as root.'
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || fail 'Pass the reviewed full 40-character SHA.'
[[ -z "$mode" || "$mode" == --resume ]] || fail 'Unknown release mode.'
if [[ "$mode" == --resume ]]; then
  [[ "$resume_backup" =~ ^/opt/dongbo/backups/account-market-[a-zA-Z0-9]+$ && -d "$resume_backup" && ! -L "$resume_backup" ]] || fail 'Invalid maintenance backup directory.'
  [[ -f "$resume_backup/before.json" && -f "$resume_backup/dongbo_erp.dump" && -f "$resume_backup/target-sha.txt" ]] || fail 'Maintenance evidence missing.'
fi
[[ -d "$app/.git" && -x "$python" && -f "$app/.env" ]] || fail 'Expected server paths missing.'
for command in git node curl sha256sum nginx systemctl flock runuser pg_dump pg_restore; do command -v "$command" >/dev/null || fail "Missing command: $command"; done
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || fail 'Another release is running.'
cd "$app"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'Tracked edits exist; preserve them first.'
[[ -z "$(git ls-files .env backend/.env)" ]] || fail 'Environment unexpectedly tracked.'
case "$(git remote get-url origin)" in
  https://github.com/kevindongbo/codex.git|https://github.com/kevindongbo/codex|git@github.com:kevindongbo/codex.git) ;;
  *) fail 'Unexpected Git origin.' ;;
esac
git fetch origin "$branch"
[[ "$(git rev-parse FETCH_HEAD)" == "$target" ]] || fail 'Remote SHA differs; checkout unchanged.'
old=$(git rev-parse HEAD)
git merge-base --is-ancestor "$old" "$target" || fail 'Divergent/newer server checkout; no overwrite.'
[[ -z "$(git diff --name-only "$old" "$target" -- backend/requirements.txt)" ]] || fail 'Dependency changes require a separate release.'
service_user=$(systemctl show "$service" -p User --value)
[[ -n "$service_user" && "$service_user" != root && "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Expected non-root web service account.'
for unit in "$service" "$worker"; do
  [[ "$(systemctl show "$unit" -p WorkingDirectory --value)" == "$app/backend" ]] || fail 'Unexpected service working directory.'
  [[ "$(systemctl show "$unit" -p EnvironmentFiles --value)" == *"$app/.env"* ]] || fail 'Unexpected service environment file.'
  if [[ -f /etc/dongbo/scheduling.env ]]; then
    [[ "$(systemctl show "$unit" -p EnvironmentFiles --value)" == *'/etc/dongbo/scheduling.env'* ]] || fail 'Scheduling environment differs.'
  fi
  if [[ "$mode" == --resume ]]; then
    if systemctl is-active --quiet "$unit"; then fail 'Resume requires both web and worker stopped; do not compare a live database.'; fi
  else systemctl is-active --quiet "$unit"; fi
done
nginx -t
if [[ "$mode" != --resume ]]; then health; verify_assets "$old"; fi
set +u; set -a
source "$app/.env" >/dev/null 2>&1
[[ ! -f /etc/dongbo/scheduling.env ]] || source /etc/dongbo/scheduling.env >/dev/null 2>&1
set +a; set -u
"$python" backend/manage.py check
if [[ "$mode" != --resume ]]; then "$python" backend/manage.py migrate --check; fi
"$python" backend/manage.py shell -c 'from django.db import connection; d=connection.settings_dict; assert connection.vendor=="postgresql" and d["NAME"]=="dongbo_erp" and d.get("HOST", "") in ("", "localhost", "127.0.0.1", "/var/run/postgresql") and str(d.get("PORT") or "5432")=="5432", "Unexpected database location"'
app_role=$("$python" -c 'import os,sys; sys.path.insert(0,"backend"); os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings"); import django; django.setup(); from django.db import connection; c=connection.cursor(); c.execute("SELECT current_user"); print(c.fetchone()[0])')
[[ -n "$app_role" ]] || fail 'Cannot resolve existing application database role.'
install -d -m 700 /opt/dongbo/backups
if [[ "$mode" == --resume ]]; then
  backup=$resume_backup
  failed_target=$(cat "$backup/target-sha.txt")
  [[ "$failed_target" =~ ^[0-9a-f]{40}$ ]] || fail 'Invalid previous release SHA.'
  git merge-base --is-ancestor "$failed_target" "$target" || fail 'Resume target is not a forward repair.'
  migration_started=1
  trap on_error ERR
  stopped=1
  pg_restore --list "$backup/dongbo_erp.dump" >/dev/null
  "$python" "$backup/release-check.py" compare "$backup/before.json"
else
  backup=$(mktemp -d /opt/dongbo/backups/account-market-XXXXXXXX)
  printf '%s\n' "$old" > "$backup/previous-sha.txt"
  printf '%s\n' "$target" > "$backup/target-sha.txt"
  git archive "$old" > "$backup/previous-code.tar"
  git show "$target:deploy/account-market-check.py" > "$backup/release-check.py"
  trap on_error ERR
  stopped=1
  systemctl stop "$worker" "$service"
  runuser -u postgres -- pg_dump --dbname=dongbo_erp --format=custom > "$backup/dongbo_erp.dump"
  pg_restore --list "$backup/dongbo_erp.dump" >/dev/null
  "$python" "$backup/release-check.py" inventory "$backup/before.json"
fi
changed=1
runtime_command git switch --detach "$target"
runtime_command node scripts/build-site.mjs
while IFS= read -r -d '' path; do runuser -u "$service_user" -- test -r "$app/$path"; done < <(git ls-files -z -- backend deploy '*.js' '*.css' '*.html')
runuser -u "$service_user" -- test -r "$app/dist/server/index.js"
"$python" backend/manage.py check
"$python" backend/manage.py makemigrations --check --dry-run
readonly admin_db='postgresql:///dongbo_erp?host=/var/run/postgresql'
# Never show database URLs, passwords or the loaded environment in the log.
migration_started=1
runuser -u postgres -- env DATABASE_URL="$admin_db" "$python" backend/manage.py migrate --noinput
runuser -u postgres -- env DATABASE_URL="$admin_db" RELEASE_DB_ROLE="$app_role" "$python" deploy/account-market-check.py grant
"$python" "$backup/release-check.py" compare "$backup/before.json"
"$python" backend/manage.py check_account_market_release
"$python" backend/manage.py check_recognition_store_release
"$python" backend/manage.py migrate --check
systemctl restart "$service" "$worker"
health
systemctl is-active --quiet "$service"
systemctl is-active --quiet "$worker"
verify_assets "$target"
"$python" deploy/verify-dashboard-reads.py
trap - ERR
printf 'ACCOUNT / MARKET CODE, MIGRATIONS, HISTORY, SERVICES, ASSETS VERIFIED AT LOCAL NGINX ORIGIN\nSHA: %s\nBackup: %s\n' "$target" "$backup"
printf 'US/MX merchant scenarios available when MARKET_V2_ENABLED=true; official leaf mappings, full carrier tariffs and real shop tax/eligibility remain gated. Signed-in acceptance is required.\n'
