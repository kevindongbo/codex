#!/usr/bin/env bash
# Revert only the 7/15/30 replenishment-window schema rename after a verified backup.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/dongbo/app}"
VENV_PYTHON="${VENV_PYTHON:-/opt/dongbo/venv/bin/python}"

if [[ "${CONFIRM_REPLENISHMENT_WINDOW_ROLLBACK:-}" != "YES" ]]; then
  echo "Set CONFIRM_REPLENISHMENT_WINDOW_ROLLBACK=YES after restoring a verified database backup." >&2
  exit 1
fi

cd "${APP_DIR}/backend"
set -a
# shellcheck disable=SC1091
source ../.env
set +a
"${VENV_PYTHON}" manage.py migrate erp 0020_tiktok_shop_connections_per_shop
systemctl restart dongbo-erp
echo "Schema rolled back to erp migration 0020. Verify /api/health/ before reopening the site."
