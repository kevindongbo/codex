#!/usr/bin/env bash
# Emergency code-only correction. No migrations, data restores or SQL writes.
set -Eeuo pipefail
set +x
umask 077
app=/opt/dongbo/app
python=/opt/dongbo/venv/bin/python
file=$app/backend/apps/erp/serializers.py
[[ $EUID == 0 && -f "$file" && -x "$python" ]] || exit 1
[[ $(git -C "$app" rev-parse HEAD) == 0f814ef9962ad328c53e4d14d05a5117ea85e57c ]] || { echo 'STOP: unexpected release'; exit 1; }
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || { echo 'STOP: another release is running'; exit 1; }
backup=$(mktemp -d /opt/dongbo/backups/purchase-list-XXXXXXXX)
cp -p "$file" "$backup/serializers.py"
echo "Code backup: $backup"
"$python" - "$file" <<'PY'
import ast, os, sys, tempfile
from pathlib import Path
p = Path(sys.argv[1])
old = b'if self.instance and self.instance.purchaser_id:'
new = b'if isinstance(self.instance, PurchaseOrder) and self.instance.purchaser_id:'
data = p.read_bytes()
if data.count(new) == 1 and old not in data:
    print('Correction already present')
    sys.exit(0)
assert data.count(old) == 1 and new not in data, 'STOP: source differs; no edit'
updated = data.replace(old, new)
ast.parse(updated)
info = p.stat()
fd, name = tempfile.mkstemp(dir=p.parent, prefix='.purchase-list-')
try:
    with os.fdopen(fd, 'wb') as f:
        f.write(updated)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(name, info.st_mode & 0o777)
    os.chown(name, info.st_uid, info.st_gid)
    os.replace(name, p)
finally:
    if os.path.exists(name):
        os.unlink(name)
print('Single-order guard corrected; database untouched')
PY
systemctl restart dongbo-erp.service
systemctl is-active --quiet dongbo-erp.service
cd "$app"
set +u; set -a
source "$app/.env" >/dev/null 2>&1
[[ ! -f /etc/dongbo/scheduling.env ]] || source /etc/dongbo/scheduling.env >/dev/null 2>&1
set +a; set -u
"$python" - <<'PY'
import json, os, sys, time, urllib.request
sys.path.insert(0, 'backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from apps.erp.authentication import issue_refresh
owner = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by('pk').first()
assert owner is not None, 'No active owner; stop for diagnosis'
token = str(issue_refresh(owner).access_token)
headers = {'Host': 'dongbokeji.com', 'X-Forwarded-Proto': 'https', 'Authorization': 'Bearer ' + token}
for attempt in range(15):
    try:
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/health/', headers=headers), timeout=5) as r:
            assert json.load(r).get('database') == 'ok'
        break
    except Exception:
        if attempt == 14:
            raise
        time.sleep(1)
for path in ('products', 'purchase-orders', 'stock-balances', 'stores', 'skus/profit-summary'):
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/' + path + '/', headers=headers), timeout=60) as r:
        value = json.load(r)
        count = len(value) if isinstance(value, list) else value.get('count', len(value.get('results', [])))
        print(path + ': HTTP 200; count=' + str(count))
print('Code correction and authenticated API reads verified. Refresh the browser to verify the UI.')
PY
