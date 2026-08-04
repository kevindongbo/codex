# ERP-PROFIT-REQ-20260805-01 阿里云部署、验证与回滚

已测试代码提交：`f5baf64555c34df11c82ac604283016afc6d749a`，实施分支：
`codex/implement-profit-settlement-strategies-20260805`。本次迁移为
`0027_profitcalculationstrategy`，新增组织级利润计算策略表及同组织唯一名称、唯一默认策略约束。

以下命令依据仓库现有运维配置编写：应用目录 `/opt/dongbo/app`、虚拟环境
`/opt/dongbo/venv`、服务 `dongbo-erp`、数据库 `dongbo_erp`。命令不会打印
`.env` 内容或任何凭据。本文件是部署手册，尚未在生产执行。

## 1. 正式部署

```bash
set -euo pipefail
APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
BRANCH=codex/implement-profit-settlement-strategies-20260805
SHA=f5baf64555c34df11c82ac604283016afc6d749a
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
if command -v npm >/dev/null 2>&1; then npm run build; elif command -v pnpm >/dev/null 2>&1; then pnpm run build; else node scripts/build-site.mjs; fi
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
SHA=f5baf64555c34df11c82ac604283016afc6d749a
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

页面验收：登录后在“利润试算”确认默认西马、买家运费开关及东马 RM8.00、手续费百分点调整、策略保存/覆盖/另存为、9 项金额明细和 MYR/CNY 同行展示；确认单商品采购订单字号变化而多商品 `<details>` 展示不变。

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
