#!/usr/bin/env bash
# Download and execute a copy outside the checkout. Never run via source.
set -Eeuo pipefail
set +x
umask 077
readonly app=/opt/dongbo/app
readonly python=/opt/dongbo/venv/bin/python
readonly service=dongbo-erp.service
readonly worker=dongbo-timetable-worker.service
readonly branch=codex/implement-course-scheduling-20260922
readonly domain=dongbokeji.com
readonly private_root=/var/lib/dongbo-timetables
readonly env_file=/etc/dongbo/scheduling.env
readonly dropin=/etc/systemd/system/dongbo-erp.service.d/50-course-scheduling.conf
readonly worker_file=/etc/systemd/system/dongbo-timetable-worker.service
readonly target=${1:-}
old=''; backup=''; changed=0; config_changed=0; worker_active=0; worker_enabled=0
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
  local asset actual expected path
  for asset in index.html app.js team.js styles.css profit-calculator.js scheduling.js scheduling.css; do
    [[ -f "$app/$asset" ]] || { [[ "$asset" == scheduling.* ]] && continue; return 1; }
    path=$asset; [[ "$asset" != index.html ]] || path=''
    expected=$(sha256sum "$app/$asset"); expected=${expected%% *}
    actual=$(curl -fsS --max-time 20 --compressed --resolve "$domain:443:127.0.0.1" \
      -H 'Cache-Control: no-cache' "https://$domain/$path?release=$1" | sha256sum) || return 1
    [[ "${actual%% *}" == "$expected" ]] || { printf 'Asset mismatch: %s\n' "$asset" >&2; return 1; }
  done
}
restore_config() {
  local path
  if [[ "$worker_enabled" == 0 ]]; then systemctl disable "$worker" 2>/dev/null || true; fi
  for path in "$env_file" "$dropin" "$worker_file"; do
    if [[ -f "$backup/config$path" ]]; then
      install -D -m 600 "$backup/config$path" "$path" || return 1
    else
      # Only the three exact, script-owned files are removed, never directories.
      rm -f -- "$path" || return 1
    fi
  done
  systemctl daemon-reload || return 1
  if [[ "$worker_enabled" == 1 ]]; then systemctl enable "$worker" || return 1; fi
}
rollback() {
  local status=$?
  trap - ERR
  set +e
  printf 'Release failed (%s). Backup: %s\n' "$status" "$backup" >&2
  if [[ "$changed" == 1 ]]; then
    systemctl stop "$worker" 2>/dev/null
    local ok=1
    if [[ "$config_changed" == 1 ]]; then restore_config || ok=0; fi
    runtime_command git -C "$app" switch --detach "$old" || ok=0
    (cd "$app" && runtime_command node scripts/build-site.mjs) || ok=0
    systemctl restart "$service" || ok=0
    if [[ "$worker_active" == 1 ]]; then systemctl start "$worker" || ok=0; fi
    health && verify_assets "$old" || ok=0
    if [[ "$ok" == 1 ]]; then printf 'CODE ROLLBACK VERIFIED: %s\n' "$old"
    else printf 'ROLLBACK NOT VERIFIED. Inspect services before retrying.\n' >&2; fi
    printf 'Database, uploaded originals and Pillow retained; no reverse migration or database restore performed.\n'
  fi
  exit "$status"
}

[[ "$EUID" == 0 ]] || fail 'Run as root in a separate bash process.'
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || fail 'Pass the reviewed full Git SHA.'
[[ -d "$app/.git" && -x "$python" && -f "$app/.env" ]] || fail 'Expected app, venv or environment missing.'
for command in git node curl sha256sum nginx systemctl flock runuser pg_dump pg_restore tar install sed id stat; do
  command -v "$command" >/dev/null || fail "Missing command: $command"
done
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || fail 'Another ERP release is running.'
cd "$app"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'Tracked edits exist; preserve them before release.'
[[ -z "$(git ls-files .env backend/.env)" ]] || fail 'Environment unexpectedly tracked.'
case "$(git remote get-url origin)" in
  https://github.com/kevindongbo/codex.git|https://github.com/kevindongbo/codex|git@github.com:kevindongbo/codex.git) ;;
  *) fail 'Unexpected Git origin.' ;;
esac
git fetch origin "$branch"
[[ "$(git rev-parse FETCH_HEAD)" == "$target" ]] || fail 'Remote SHA changed; no checkout performed.'
old=$(git rev-parse HEAD)
git merge-base --is-ancestor "$old" "$target" || fail 'Divergent/newer server history; no overwrite allowed.'
while IFS= read -r path; do
  [[ "$path" == backend/apps/erp/migrations/0038_course_work_scheduling.py ]] || fail 'Unexpected migration change; review first.'
done < <(git diff --name-only "$old" "$target" -- backend/apps/erp/migrations)
[[ "$(git show "$old:backend/requirements.txt" | sed '/^Pillow[<=>]/d')" == "$(git show "$target:backend/requirements.txt" | sed '/^Pillow[<=>]/d')" ]] || fail 'Non-Pillow dependency changes require separate review.'
[[ "$(systemctl show "$service" -p WorkingDirectory --value)" == "$app/backend" ]] || fail 'Unexpected web working directory.'
[[ "$(systemctl show "$service" -p EnvironmentFiles --value)" == *"$app/.env"* ]] || fail 'Unexpected web environment configuration.'
service_user=$(systemctl show "$service" -p User --value)
[[ -n "$service_user" && "$service_user" != root && "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Expected an existing non-root web service user.'
service_group=$(systemctl show "$service" -p Group --value)
service_group=${service_group:-$(id -gn "$service_user")}
[[ "$service_group" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Unexpected service group.'
systemctl is-active --quiet "$service" || fail 'Web service unhealthy before release.'
if systemctl is-active --quiet "$worker"; then worker_active=1; fi
if systemctl is-enabled --quiet "$worker" 2>/dev/null; then worker_enabled=1; fi
for path in "$private_root" "$env_file" "$dropin" "$worker_file"; do
  [[ ! -L "$path" ]] || fail "Refusing symlink: $path"
done
nginx -t
health || fail 'Existing API health check failed.'
verify_assets "$old" || fail 'Existing Nginx serving path does not match checkout.'
set +u
set -a
source "$app/.env" >/dev/null 2>&1 || fail 'Could not load production environment.'
if [[ -f "$env_file" ]]; then source "$env_file" >/dev/null 2>&1 || fail 'Could not load existing scheduling environment.'; fi
set +a
set -u
[[ -n "${DJANGO_SECRET_KEY:-}" && -n "${DATABASE_URL:-}" ]] || fail 'Production environment incomplete.'
[[ -z "${SCHEDULING_PRIVATE_ROOT:-}" || "$SCHEDULING_PRIVATE_ROOT" == "$private_root" ]] || fail 'Existing private storage uses another path; preserve and review before release.'
"$python" backend/manage.py check
"$python" backend/manage.py migrate --check
[[ "$("$python" backend/manage.py shell -c 'from django.db import connection; print(connection.settings_dict["NAME"])' | tail -n 1)" == dongbo_erp ]] || fail 'Unexpected database.'
"$python" backend/manage.py shell -c 'from django.db import connection; d=connection.settings_dict; assert connection.vendor == "postgresql" and d.get("HOST", "") in ("", "localhost", "127.0.0.1", "/var/run/postgresql") and str(d.get("PORT") or "5432") == "5432", "Remote/custom PostgreSQL requires a reviewed backup command"'
if [[ -d "$private_root" ]]; then
  [[ "$(stat -c %U "$private_root")" == "$service_user" ]] || fail 'Existing originals owned by a different account; no ownership overwrite allowed.'
fi
# Pillow is the only new dependency; do not upgrade the existing Django stack.
if ! "$python" -c 'import PIL; assert 11 <= int(PIL.__version__.split(".")[0]) < 13' 2>/dev/null; then
  runtime_command "$python" -m pip install --only-binary=:all: 'Pillow>=11.0,<13.0'
fi
install -d -m 700 /opt/dongbo/backups
backup=$(mktemp -d /opt/dongbo/backups/course-scheduling-XXXXXXXX)
printf '%s\n' "$old" > "$backup/previous-sha.txt"
printf '%s\n' "$target" > "$backup/target-sha.txt"
for path in "$env_file" "$dropin" "$worker_file"; do
  if [[ -f "$path" ]]; then install -D -m 600 "$path" "$backup/config$path"; fi
done
git archive "$old" > "$backup/previous-code.tar"
trap rollback ERR
changed=1
if [[ "$worker_active" == 1 ]]; then systemctl stop "$worker"; fi
systemctl stop "$service"
runuser -u postgres -- pg_dump --dbname=dongbo_erp --format=custom > "$backup/dongbo_erp.dump"
pg_restore --list "$backup/dongbo_erp.dump" >/dev/null
if [[ -d "$private_root" ]]; then tar -C /var/lib -cf "$backup/private-timetables.tar" dongbo-timetables; fi
runtime_command git switch --detach "$target"
node --check scheduling.js
runtime_command node scripts/build-site.mjs
# Git checkout uses 022 above; verify all tracked Python/source assets are readable.
while IFS= read -r -d '' path; do
  runuser -u "$service_user" -- test -r "$app/$path"
done < <(git ls-files -z -- backend '*.js' '*.css' '*.html')
runuser -u "$service_user" -- test -r "$app/dist/server/index.js"
install -d -m 700 -o "$service_user" -g "$service_group" "$private_root"
runuser -u "$service_user" -- test -w "$private_root"
export SCHEDULING_ENABLED=true SCHEDULING_PRIVATE_ROOT="$private_root"
"$python" backend/manage.py check_scheduling_release
"$python" backend/manage.py migrate erp 0038_course_work_scheduling --noinput
"$python" backend/manage.py check_scheduling_release --expect-migrated
config_changed=1
install -d -m 755 /etc/dongbo /etc/systemd/system/dongbo-erp.service.d
printf 'SCHEDULING_ENABLED=true\nSCHEDULING_PRIVATE_ROOT=%s\n' "$private_root" > "$env_file"
printf '[Service]\nEnvironmentFile=%s\nReadWritePaths=%s\n' "$env_file" "$private_root" > "$dropin"
cat > "$worker_file" <<UNIT
[Unit]
Description=Dongbo private timetable recognition worker
After=network.target
[Service]
Type=simple
User=$service_user
Group=$service_group
WorkingDirectory=$app/backend
EnvironmentFile=$app/.env
EnvironmentFile=$env_file
ExecStart=$python $app/backend/manage.py run_timetable_worker --poll-seconds 3
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$private_root
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl restart "$service"
health
systemctl enable --now "$worker"
sleep 3
systemctl is-active --quiet "$service"
systemctl is-active --quiet "$worker"
verify_assets "$target"
trap - ERR
printf 'SCHEDULING RELEASE VERIFIED AT LOCAL NGINX ORIGIN\nSHA: %s\nBackup: %s\n' "$target" "$backup"
printf 'Migration 0038 verified. Originals/private audit retained. Public browser and real vision-provider acceptance still required.\n'
printf 'Visit https://%s/ and configure the term and existing vision model as superadministrator.\n' "$domain"
