#!/usr/bin/env bash
# Roll back only migration 0020 after restoring a verified database backup.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/dongbo/app}"
VENV_PYTHON="${VENV_PYTHON:-/opt/dongbo/venv/bin/python}"

if [[ "${CONFIRM_TIKTOK_MULTISHOP_ROLLBACK:-}" != "YES" ]]; then
  echo "Set CONFIRM_TIKTOK_MULTISHOP_ROLLBACK=YES after restoring the database backup." >&2
  exit 1
fi

cd "${APP_DIR}/backend"
set -a
# shellcheck disable=SC1091
source ../.env
set +a
"${VENV_PYTHON}" manage.py migrate erp 0019_alphashopconfig
systemctl restart dongbo-erp
echo "Schema rolled back to erp migration 0019. Verify /api/health/ before reopening the site."
