# ERP-PROFIT-REQ-20260805-01 阿里云部署、验证与回滚

已测试代码提交：`00d319a9f0f3f57521c2619dcf988d751be13e4b`，实施分支：
`codex/implement-profit-strategy-ui-fixes-20260805`。本次为利润策略界面和 API
行为修正，不新增数据库迁移；部署前仍校验既有策略表迁移
`0027_profitcalculationstrategy` 已应用。

以下命令依据仓库现有运维配置编写：应用目录 `/opt/dongbo/app`、虚拟环境
`/opt/dongbo/venv`、服务 `dongbo-erp`、数据库 `dongbo_erp`。命令不会打印
`.env` 内容或任何凭据。本文件是部署手册，尚未在生产执行。

## 1. 正式部署

```bash
set -euo pipefail
APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
BRANCH=codex/implement-profit-strategy-ui-fixes-20260805
SHA=00d319a9f0f3f57521c2619dcf988d751be13e4b
DB_NAME=dongbo_erp
APP_SERVICE=dongbo-erp
cd "$APP"
REMOTE=$(git remote | while read -r name; do url=$(git remote get-url "$name"); case "$url" in *github.com/kevindongbo/codex*) printf '%s\n' "$name"; break;; esac; done)
test -n "$REMOTE"
test -z "$(git status --porcelain)"
git fetch "$REMOTE" "$BRANCH"
git cat-file -e "$SHA^{commit}"
test "$(git rev-parse "$SHA")" = "$SHA"
git merge-base --is-ancestor "$SHA" "$REMOTE/$BRANCH"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/opt/dongbo/backups/$STAMP
sudo mkdir -p "$BACKUP_DIR"
git rev-parse HEAD | sudo tee "$BACKUP_DIR/code-commit.txt" >/dev/null
sudo tar --exclude=.git --exclude=.venv --exclude=.env -C /opt/dongbo -czf "$BACKUP_DIR/app.tar.gz" app
sudo -u postgres pg_dump -Fc "$DB_NAME" > "/tmp/${DB_NAME}-${STAMP}.dump"
sudo mv "/tmp/${DB_NAME}-${STAMP}.dump" "$BACKUP_DIR/${DB_NAME}.dump"
git checkout --detach "$SHA"
test "$(git rev-parse HEAD)" = "$SHA"
"$VENV/bin/pip" install -r "$APP/backend/requirements.txt"
NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]"); fi
if [ "$NODE_MAJOR" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get remove -y libnode-dev
  sudo apt-get -f install -y
  sudo dpkg --configure -a
  sudo apt-get install -y nodejs
fi
node -e "const major=Number(process.versions.node.split('.')[0]); if (major < 18) { throw new Error('Node.js 18+ is required'); }"
npm run build
set -a
. "$APP/.env"
set +a
cd "$APP/backend"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput
sudo systemctl restart "$APP_SERVICE"
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl is-active --quiet "$APP_SERVICE"
"$VENV/bin/python" manage.py showmigrations erp | grep -F '[X] 0027_profitcalculationstrategy'
curl -fsS --max-time 15 http://127.0.0.1:8000/api/health/
printf '\nDEPLOY_SUCCESS SHA=%s\nBACKUP_DIR=%s\n' "$SHA" "$BACKUP_DIR"
```

## 2. 部署后验证

```bash
set -euo pipefail
APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
SHA=00d319a9f0f3f57521c2619dcf988d751be13e4b
APP_SERVICE=dongbo-erp
test "$(git -C "$APP" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$APP" status --porcelain)"
sudo systemctl is-active --quiet "$APP_SERVICE"
sudo nginx -t
curl -fsS --max-time 15 http://127.0.0.1:8000/api/health/
curl -fsSI --max-time 20 https://dongbokeji.com/ | head -n 1
set -a
. "$APP/.env"
set +a
"$VENV/bin/python" "$APP/backend/manage.py" check
"$VENV/bin/python" "$APP/backend/manage.py" showmigrations erp | grep -F '[X] 0027_profitcalculationstrategy'
sudo journalctl -u "$APP_SERVICE" --since '15 minutes ago' -n 120 --no-pager
sudo tail -n 100 /var/log/nginx/error.log
printf 'VERIFY_SUCCESS SHA=%s\n' "$SHA"
```

页面验收：登录后在“利润试算”确认策略名称标签栏、点击策略后默认策略持久化、新建/覆盖/另存/删除策略弹窗、买家收货地区仅在策略弹窗内出现；确认 BXP 与买家运费同一行、手续费调整位于第一行、顶部利润卡主币/≈辅助币、左侧费用单币、右侧九项双币，以及多项费用默认折叠和 SVG 箭头。SKU 输入、九项汇总和利润公式应保持原口径。

## 3. 一键回滚

恢复数据库会丢失部署后写入的数据。请使用正式部署输出的 `BACKUP_DIR`，并确认后再执行。

```bash
set -euo pipefail
APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
DB_NAME=dongbo_erp
APP_SERVICE=dongbo-erp
read -r -p '输入正式部署输出的 BACKUP_DIR: ' BACKUP_DIR
case "$BACKUP_DIR" in /opt/dongbo/backups/*) ;; *) echo '备份目录不合法' >&2; exit 1;; esac
test -f "$BACKUP_DIR/code-commit.txt"
test -f "$BACKUP_DIR/${DB_NAME}.dump"
test -f "$BACKUP_DIR/app.tar.gz"
read -r -p '恢复数据库会丢失部署后的新增数据；输入 ROLLBACK 继续: ' CONFIRM
test "$CONFIRM" = ROLLBACK
PREVIOUS_SHA=$(tr -d '[:space:]' < "$BACKUP_DIR/code-commit.txt")
cd "$APP"
git cat-file -e "$PREVIOUS_SHA^{commit}"
sudo systemctl stop "$APP_SERVICE"
sudo -u postgres pg_restore --clean --if-exists --no-owner -d "$DB_NAME" "$BACKUP_DIR/${DB_NAME}.dump"
git checkout --detach "$PREVIOUS_SHA"
test "$(git rev-parse HEAD)" = "$PREVIOUS_SHA"
"$VENV/bin/pip" install -r "$APP/backend/requirements.txt"
set -a
. "$APP/.env"
set +a
cd "$APP/backend"
"$VENV/bin/python" manage.py collectstatic --noinput
sudo systemctl start "$APP_SERVICE"
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl is-active --quiet "$APP_SERVICE"
curl -fsS --max-time 15 http://127.0.0.1:8000/api/health/
sudo journalctl -u "$APP_SERVICE" -n 100 --no-pager
printf '\nROLLBACK_SUCCESS SHA=%s DATABASE_BACKUP=%s\n' "$PREVIOUS_SHA" "$BACKUP_DIR/${DB_NAME}.dump"
```
