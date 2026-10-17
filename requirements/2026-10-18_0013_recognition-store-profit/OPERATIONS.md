# 服务器验收与回滚

部署使用最终交付中绑定SHA的整段脚本；本文件不把分支名当作永久版本。发布脚本硬编码本次分支，不用于其他功能发布。

## 真实识别验收

发布后在ERP“原始凭证”创建草稿，学期设置中选择支持图片的已配置模型。点“重新识别”；若看到持续排队，检查 `dongbo-timetable-worker.service`。401/403检查服务端密钥及权限，404检查API路径/模型，400检查模型视觉能力。供应商错误不自动改成“无课”。

模型配置中的供应商参数会传入请求，固定关闭stream；工具调用、流式专用参数、多个候选以及覆盖模型/消息/鉴权的参数会在调用前拒绝。修改这些参数应在ERP模型设置中完成。发布脚本会检查网页与worker使用相同预期环境文件，并只读核验本次保存/识别所需表权限；缺权限时停止并尝试回退代码，不自动扩大数据库权限。成功输出仅证明代码、服务和源站资源核验通过。

如需在服务器独立检查，先取得目标草稿UUID，替换下面占位符。此命令真实调用该草稿所属学期配置的API，会产生费用；最多尝试3次，只输出格子数量，保留原图和草稿，不发布排班。不输出环境文件、API密钥或课程原文。

显式次数允许重试模型输出格式错误和空候选；鉴权、地址不存在和配置错误立即停止，不通过重复付费调用掩盖配置问题。worker原有暂时错误自动重试策略不变。

```bash
bash --noprofile --norc <<'BASH'
set -Eeuo pipefail
set +x
cd /opt/dongbo/app
import_id='<TIMETABLE_IMPORT_UUID>'
[[ "$import_id" =~ ^[0-9a-fA-F-]{36}$ ]] || { printf '请替换目标草稿UUID。\n' >&2; exit 1; }
set +u
set -a
source /opt/dongbo/app/.env >/dev/null 2>&1
[[ ! -f /etc/dongbo/scheduling.env ]] || source /etc/dongbo/scheduling.env >/dev/null 2>&1
set +a
set -u
/opt/dongbo/venv/bin/python backend/manage.py verify_timetable_recognition --import-id "$import_id" --attempts 3
BASH
```

识别到课程只表示API返回候选，需逐格检查与原图一致后本人确认。裁切或没有周末列不自动推断无课。若原先手工把84格设为无课，必须重新识别并校对后发布，不能拿旧全free草稿当作模型正确结果。

## 商品验收

编辑商品，补齐每个SKU的利润类目/包装重量/采购成本/默认佣金；添加店铺售价后选择正确SKU和店铺，佣金空继承、0为零。保存，刷新后再打开，验证售价/佣金/店铺保留；列表展开按店铺核对毛利和保本ROI。缺参数会列出原因，毛利不大于0时保本ROI无正解，不伪造0。

## 成功发布后的人工代码回滚

用户明确选择回滚时执行；必须替换当次当前SHA和发布日志中的精确备份目录，发现有后续更新立即停止。模板只回滚相容代码，不恢复数据库、不删除原图。Bash语法已检查；本轮没有执行生产回滚。

```bash
bash --noprofile --norc <<'BASH'
set -Eeuo pipefail
set +x
umask 077
app=/opt/dongbo/app
expected_current='<CURRENT_VERIFIED_FULL_SHA>'
release_backup='/opt/dongbo/backups/<EXACT_RELEASE_BACKUP_DIRECTORY>'
[[ "$EUID" == 0 && "$expected_current" =~ ^[0-9a-f]{40}$ ]] || exit 1
case "$release_backup" in *'<'*) printf '请替换精确备份目录。\n' >&2; exit 1 ;; esac
cd "$app"
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9
test -z "$(git status --porcelain --untracked-files=no)"
test "$(git rev-parse HEAD)" = "$expected_current"
resolved=$(realpath -e "$release_backup")
case "$resolved" in /opt/dongbo/backups/recognition-store-profit-*) ;; *) exit 1 ;; esac
old_sha=$(head -n 1 "$resolved/previous-sha.txt")
[[ "$old_sha" =~ ^[0-9a-f]{40}$ ]]
git cat-file -e "$old_sha^{commit}"
git merge-base --is-ancestor "$old_sha" "$expected_current"
test -z "$(git diff --name-only "$old_sha" "$expected_current" -- backend/apps/erp/migrations backend/requirements.txt)"
backup=$(mktemp -d /opt/dongbo/backups/manual-repair-rollback-XXXXXXXX)
printf '%s\n' "$expected_current" > "$backup/previous-sha.txt"
git archive "$expected_current" > "$backup/previous-code.tar"
changed=0
restore_current() {
  status=$?
  trap - ERR
  set +e
  if [ "$changed" = 1 ]; then
    (umask 022; git switch --detach "$expected_current"; node scripts/build-site.mjs)
  fi
  systemctl restart dongbo-erp.service dongbo-timetable-worker.service
  printf '回滚失败，已尝试恢复原版本；必须核验服务与健康。\n' >&2
  exit "$status"
}
trap restore_current ERR
changed=1
systemctl stop dongbo-timetable-worker.service dongbo-erp.service
runuser -u postgres -- pg_dump --dbname=dongbo_erp --format=custom > "$backup/dongbo_erp.dump"
pg_restore --list "$backup/dongbo_erp.dump" >/dev/null
(umask 022; git switch --detach "$old_sha"; node scripts/build-site.mjs)
nginx -t
systemctl restart dongbo-erp.service dongbo-timetable-worker.service
healthy=0
for attempt in {1..30}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health/ 2>/dev/null |
    /opt/dongbo/venv/bin/python -c 'import json,sys; x=json.load(sys.stdin); sys.exit(not(x.get("status")=="ok" and x.get("database")=="ok"))' 2>/dev/null; then healthy=1; break; fi
  sleep 1
done
test "$healthy" = 1
systemctl is-active --quiet dongbo-erp.service
systemctl is-active --quiet dongbo-timetable-worker.service
for asset in index.html app.js team.js styles.css profit-calculator.js scheduling.js scheduling.css; do
  path=$asset; [ "$asset" != index.html ] || path=''
  expected=$(sha256sum "$app/$asset"); expected=${expected%% *}
  actual=$(curl -fsS --max-time 20 --compressed --resolve dongbokeji.com:443:127.0.0.1 "https://dongbokeji.com/$path?rollback=$old_sha" | sha256sum)
  test "${actual%% *}" = "$expected"
done
trap - ERR
printf '代码回滚源站核验通过：%s；备份：%s；数据库和原图保留。\n' "$old_sha" "$backup"
BASH
```
