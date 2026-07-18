#!/usr/bin/env bash
set -euo pipefail

# This removes the AI queue and the new 3-day/AI settings columns. Restore the
# verified pre-release PostgreSQL backup first if any queued-job history matters.
if [[ "${CONFIRM_REPLENISHMENT_AI_ROLLBACK:-}" != "YES" ]]; then
  echo "Refusing rollback. Set CONFIRM_REPLENISHMENT_AI_ROLLBACK=YES after restoring a verified backup."
  exit 2
fi

cd /opt/dongbo/app/backend
set -a
source ../.env
set +a
/opt/dongbo/venv/bin/python manage.py migrate erp 0021

