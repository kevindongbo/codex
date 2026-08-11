# 阿里云黑框部署模板

> 只有 Codex 完成修改、测试通过并 push 后才能执行。
>
> 正式执行前把 `<FINAL_SHA>` 替换成 Codex 最终回复中的 40 位 commit SHA。
>
> 目标分支：`codex/erp-ui-workflow-fix-20260812-0144`
>
> 服务器目录按当前部署文档：`/opt/dongbo/app`

## 一、先检查，不修改服务器

```bash
cd /opt/dongbo/app
pwd
git status --short
git branch --show-current
git rev-parse HEAD
systemctl is-active dongbo-erp
```

如果 `git status --short` 有任何你不认识的本地改动，先停止，不要继续部署。

---

## 二、正式部署命令

先将下面：

```text
FINAL_SHA=<FINAL_SHA>
```

替换成 Codex 最终 SHA。

然后整段执行：

```bash
set -euo pipefail

APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
BRANCH='codex/erp-ui-workflow-fix-20260812-0144'
FINAL_SHA='<FINAL_SHA>'
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/opt/dongbo/backups/$TS

cd "$APP"

# 1. 安全检查：服务器工作区必须干净
if [ -n "$(git status --porcelain)" ]; then
  echo 'ERROR: /opt/dongbo/app 存在未提交修改，停止部署。'
  git status --short
  exit 1
fi

# 2. 创建部署前备份
mkdir -p "$BACKUP"
git rev-parse HEAD | tee "$BACKUP/code-commit.txt"
tar --exclude=.git --exclude=.venv --exclude=.env -C /opt/dongbo -czf "$BACKUP/app.tar.gz" app
sudo -u postgres pg_dump -Fc dongbo_erp > "$BACKUP/dongbo_erp.dump"

echo "Backup created: $BACKUP"

# 3. 获取 Codex 最终代码
git fetch origin "$BRANCH"
git switch "$BRANCH"
git pull --ff-only origin "$BRANCH"

# 4. 强校验：服务器拿到的必须正好是审核后的 Codex SHA
ACTUAL_SHA=$(git rev-parse HEAD)
echo "Expected SHA: $FINAL_SHA"
echo "Actual SHA:   $ACTUAL_SHA"
if [ "$ACTUAL_SHA" != "$FINAL_SHA" ]; then
  echo 'ERROR: GitHub 分支 HEAD 与准备部署的最终 SHA 不一致，停止部署。'
  exit 1
fi

# 5. 安装依赖
"$VENV/bin/pip" install -r backend/requirements.txt

# 6. Django 检查 + 数据库 migration
cd "$APP/backend"
set -a
source "$APP/.env"
set +a

"$VENV/bin/python" manage.py check
"$VENV/bin/python" manage.py migrate
"$VENV/bin/python" manage.py collectstatic --noinput

# 7. 重启服务
systemctl restart dongbo-erp
nginx -t
systemctl reload nginx

# 8. 健康检查
sleep 3
systemctl is-active dongbo-erp
curl -fsS http://127.0.0.1:8000/api/health/
curl -I --max-time 15 https://dongbokeji.com/

# 9. 输出部署信息
cd "$APP"
echo 'DEPLOY SUCCESS'
echo "Branch: $(git branch --show-current)"
echo "SHA:    $(git rev-parse HEAD)"
echo "Backup: $BACKUP"
```

---

## 三、部署后人工验收

必须至少在浏览器检查：

```text
1. 店铺：新增店铺 → 立即显示 → F5 后仍显示。
2. 订单：选择仓库不再输入 UUID，可以看到库存和缺口。
3. 订单：取消可以真正停止 ERP 履约并释放锁库。
4. 库存：库存列表能看到在途库存。
5. 调拨：可以编辑物流包/物流单号，确认发出，部分收货。
6. 利润试算：修改配置后出现已保存，F5 后配置仍存在。
```

---

## 四、出现问题时不要直接 migrate 回退

优先停止继续操作并记录：

```bash
cd /opt/dongbo/app
git rev-parse HEAD
systemctl status dongbo-erp --no-pager -l
journalctl -u dongbo-erp -n 200 --no-pager
```

部署脚本已经在：

```text
/opt/dongbo/backups/<时间>/
```

保留：

```text
code-commit.txt
app.tar.gz
dongbo_erp.dump
```

如果本次包含 migration，数据库回滚必须先根据本次 migration 内容判断；不要只执行 `git checkout` 就认为数据库已经回滚。

正式回滚前，应把 Codex 最终 migration 列表和部署前 `code-commit.txt` 发回审查后再执行。