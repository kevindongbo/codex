#!/usr/bin/env bash
set -euo pipefail

# Usage (run as root on the server):
#   bash deploy_replenishment_automation.sh <immutable-github-commit>
# This intentionally uses public raw GitHub files and never needs server-side
# Git credentials. It backs up code/database before touching production.

commit="${1:?pass the immutable GitHub commit SHA}"
app_dir="/opt/dongbo/app"
repo_raw="https://raw.githubusercontent.com/kevindongbo/codex/${commit}"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="/opt/dongbo/backups/${timestamp}"
stage_dir="$(mktemp -d /tmp/dongbo-replenishment.XXXXXX)"
trap 'rm -rf "$stage_dir"' EXIT

test -d "$app_dir/backend"
mkdir -p "$backup_dir"
tar --exclude=.git --exclude=.venv --exclude=.env -C /opt/dongbo -czf "$backup_dir/app.tar.gz" app
sudo -u postgres pg_dump -Fc dongbo_erp > "$backup_dir/dongbo_erp.dump"
printf '%s\n' "$commit" > "$backup_dir/release-commit.txt"

files=(
  app.js
  team.js
  index.html
  DEPLOYMENT_ERP_OPERATIONS.md
  backend/apps/erp/apps.py
  backend/apps/erp/models.py
  backend/apps/erp/replenishment.py
  backend/apps/erp/replenishment_automation.py
  backend/apps/erp/signals.py
  backend/apps/erp/serializers.py
  backend/apps/erp/urls.py
  backend/apps/erp/views.py
  backend/apps/erp/migrations/0022_replenishment_ai_automation.py
  backend/apps/erp/management/__init__.py
  backend/apps/erp/management/commands/__init__.py
  backend/apps/erp/management/commands/process_replenishment_ai.py
  backend/scripts/dongbo-replenishment-ai.service
  backend/scripts/dongbo-replenishment-ai.timer
  backend/scripts/rollback_replenishment_ai_0022.sh
)

for file in "${files[@]}"; do
  mkdir -p "$stage_dir/$(dirname "$file")"
  curl --fail --silent --show-error --location "$repo_raw/$file" -o "$stage_dir/$file"
done

for file in "${files[@]}"; do
  install -D -m 0644 "$stage_dir/$file" "$app_dir/$file"
done

cd "$app_dir/backend"
set -a
source ../.env
set +a
/opt/dongbo/venv/bin/python manage.py migrate
/opt/dongbo/venv/bin/python manage.py collectstatic --noinput

install -m 0644 scripts/dongbo-replenishment-ai.service /etc/systemd/system/dongbo-replenishment-ai.service
install -m 0644 scripts/dongbo-replenishment-ai.timer /etc/systemd/system/dongbo-replenishment-ai.timer
systemctl daemon-reload
systemctl enable --now dongbo-replenishment-ai.timer
systemctl restart dongbo-erp
nginx -t
systemctl reload nginx
sleep 5
systemctl is-active dongbo-erp
systemctl is-active dongbo-replenishment-ai.timer
curl -fsS http://127.0.0.1:8000/api/health/
echo "Deployment complete. Backups: $backup_dir"

