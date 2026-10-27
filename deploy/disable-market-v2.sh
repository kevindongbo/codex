#!/usr/bin/env bash
# Logical rollback: preserve departure generations, prices and profit snapshots.
set -Eeuo pipefail
set +x
umask 077
[[ "$EUID" == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || { echo 'Another release is running.' >&2; exit 1; }
readonly service=dongbo-erp.service
readonly folder=/etc/systemd/system/dongbo-erp.service.d
readonly path="$folder/90-market-v2-disable.conf"
[[ "$(systemctl show "$service" -p WorkingDirectory --value)" == /opt/dongbo/app/backend ]] || { echo 'Unexpected service.' >&2; exit 1; }
# EnvironmentFile takes precedence over Environment. A final, dedicated file
# overrides the feature flag only, without editing production credentials.
install -d -m 755 "$folder"
install -d -m 700 /etc/dongbo
printf 'MARKET_V2_ENABLED=false\n' > /etc/dongbo/market-v2-disabled.env
chmod 600 /etc/dongbo/market-v2-disabled.env
printf '[Service]\nEnvironmentFile=/etc/dongbo/market-v2-disabled.env\n' > "$path"
chmod 644 "$path"
systemctl daemon-reload
systemctl restart "$service"
systemctl is-active --quiet "$service"
curl -fsS --max-time 10 http://127.0.0.1:8000/api/health/ |
  /opt/dongbo/venv/bin/python -c 'import json,sys; x=json.load(sys.stdin); sys.exit(not(x.get("status")=="ok" and x.get("database")=="ok"))'
printf 'US/MX feature disabled; new authentication and all historical data retained. MY compatibility remains available.\n'
