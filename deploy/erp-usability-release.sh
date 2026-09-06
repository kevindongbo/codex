#!/usr/bin/env bash
# Execute a downloaded copy, not this file inside the checkout being switched.
set -Eeuo pipefail
set +x
umask 077

readonly release_app=/opt/dongbo/app
readonly release_python=/opt/dongbo/venv/bin/python
readonly release_service=dongbo-erp.service
readonly release_branch=codex/erp-usability-audit-20260906
readonly release_domain=dongbokeji.com
readonly release_target="${1:-}"
release_changed=0
release_backup=''
release_old=''

fail() { printf '%s\n' "$*" >&2; exit 1; }
health() {
  local attempt
  for attempt in {1..30}; do
    if curl --silent --fail --max-time 3 http://127.0.0.1:8000/api/health/ |
       "$release_python" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and d.get("database")=="ok" else 1)' 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}
origin_file() {
  curl --fail --silent --show-error --max-time 20 --compressed \
    --resolve "$release_domain:443:127.0.0.1" \
    -H 'Cache-Control: no-cache' "https://$release_domain/$1?release=$2"
}
verify_assets() {
  local asset local_hash served_hash url_path
  for asset in index.html app.js team.js styles.css profit-calculator.js; do
    url_path="$asset"
    [[ "$asset" != index.html ]] || url_path=''
    local_hash=$(sha256sum "$release_app/$asset")
    local_hash=${local_hash%% *}
    served_hash=$(origin_file "$url_path" "$1" | sha256sum) || return 1
    served_hash=${served_hash%% *}
    if [[ "$local_hash" != "$served_hash" ]]; then
      printf 'STOP: Nginx served %s does not match %s. No cache guess or directory overwrite.\n' "$asset" "$release_app/$asset" >&2
      return 1
    fi
  done
}
on_error() {
  local status=$?
  trap - ERR
  set +e
  printf 'Release failed (exit %s). Backup: %s\n' "$status" "$release_backup" >&2
  if [[ "$release_changed" == 1 ]]; then
    # Code-only rollback. Never restore/fake/drop the production database.
    if git -C "$release_app" switch --detach "$release_old" &&
       (cd "$release_app" && node scripts/build-site.mjs) &&
       systemctl restart "$release_service" && health && verify_assets "$release_old"; then
      printf 'Code rollback verified: %s. Database untouched.\n' "$release_old" >&2
    else
      printf 'ROLLBACK NOT VERIFIED. Stop and inspect services; do not restore the database.\n' >&2
    fi
  fi
  exit "$status"
}

[[ "$EUID" == 0 ]] || fail 'Run as root in a separate bash process.'
[[ "$release_target" =~ ^[0-9a-f]{40}$ ]] || fail 'Pass the exact reviewed 40-character Git SHA.'
[[ -d "$release_app/.git" && -x "$release_python" && -f "$release_app/.env" ]] || fail 'Expected application, Python or .env is missing.'
for command in git node curl sha256sum nginx systemctl flock; do command -v "$command" >/dev/null || fail "Missing command: $command"; done
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || fail 'Another release is running.'
cd "$release_app"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'Tracked working-tree changes exist; preserve and review them first.'
[[ -z "$(git ls-files .env backend/.env)" ]] || fail 'Environment file is unexpectedly tracked; stop.'
case "$(git remote get-url origin)" in
  https://github.com/kevindongbo/codex.git|https://github.com/kevindongbo/codex|git@github.com:kevindongbo/codex.git) ;;
  *) fail 'Unexpected origin repository.' ;;
esac
git fetch origin "$release_branch"
[[ "$(git rev-parse FETCH_HEAD)" == "$release_target" ]] || fail 'Remote SHA differs from the reviewed release. No checkout performed.'
release_old=$(git rev-parse HEAD)
git merge-base --is-ancestor "$release_old" "$release_target" || fail 'Server has divergent/newer history; no reset or overwrite allowed.'
git diff --quiet "$release_old" "$release_target" -- backend/apps/erp/migrations backend/requirements.txt || fail 'Migration/dependency changes require a separate reviewed deployment.'
[[ "$(systemctl show "$release_service" -p WorkingDirectory --value)" == "$release_app/backend" ]] || fail 'Unexpected service WorkingDirectory.'
[[ "$(systemctl show "$release_service" -p EnvironmentFiles --value)" == *"$release_app/.env"* ]] || fail 'Service does not reference the expected production .env.'
systemctl is-active --quiet "$release_service" || fail 'Service was not healthy before release.'
nginx -t
health || fail 'Backend health check failed before release.'
verify_assets "$release_old" || fail 'Frontend serving path/version is inconsistent before release.'

# Do not echo, rewrite or replace any production secret.
set +u
set -a
source "$release_app/.env" >/dev/null 2>&1 || fail 'Could not load production environment.'
set +a
set -u
[[ -n "${DJANGO_SECRET_KEY:-}" && -n "${DATABASE_URL:-}" ]] || fail 'Production environment is incomplete.'
[[ "$DATABASE_URL" == postgres://* || "$DATABASE_URL" == postgresql://* ]] || fail 'Expected production PostgreSQL configuration.'
"$release_python" backend/manage.py check
"$release_python" backend/manage.py migrate --check

mkdir -p /opt/dongbo/backups
release_backup=$(mktemp -d /opt/dongbo/backups/erp-usability-XXXXXXXX)
printf '%s\n' "$release_old" > "$release_backup/previous-sha.txt"
printf '%s\n' "$release_target" > "$release_backup/target-sha.txt"
git archive "$release_old" > "$release_backup/previous-code.tar"
trap on_error ERR
git switch --detach "$release_target"
release_changed=1
node --check app.js
node --check team.js
node scripts/build-site.mjs
"$release_python" backend/manage.py check
"$release_python" backend/manage.py migrate --check
systemctl restart "$release_service"
health
systemctl is-active --quiet "$release_service"
verify_assets "$release_target"
trap - ERR
printf 'RELEASE VERIFIED AT LOCAL NGINX ORIGIN\nSHA: %s\nBackup: %s\nDatabase unchanged; no migrations, collectstatic, dependency installs or timer changes.\n' "$release_target" "$release_backup"
printf 'Public CDN/browser cache and signed-in business acceptance remain to be verified at https://%s/\n' "$release_domain"
