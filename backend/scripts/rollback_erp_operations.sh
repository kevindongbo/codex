#!/usr/bin/env bash
# Roll back schema changes introduced by migrations 0017 and 0018.
# Run only after restoring a verified pre-deployment PostgreSQL backup.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/dongbo/app}"
VENV_PYTHON="${VENV_PYTHON:-/opt/dongbo/venv/bin/python}"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "Missing ${APP_DIR}/.env; refusing to run." >&2
  exit 1
fi

if [[ "${CONFIRM_ERP_OPERATIONS_ROLLBACK:-}" != "YES" ]]; then
  echo "Set CONFIRM_ERP_OPERATIONS_ROLLBACK=YES after restoring the database backup." >&2
  exit 1
fi

cd "${APP_DIR}/backend"
set -a
# shellcheck disable=SC1091
source ../.env
set +a
"${VENV_PYTHON}" manage.py migrate erp 0016_productimage_data_url
systemctl restart dongbo-erp
echo "Schema rolled back to erp migration 0016. Verify /api/health/ before reopening the site."
