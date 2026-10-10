# 2026-10-11 优化版本：部署与回滚

适用既有已上线的课程排班环境，不用于首次安装。实现分支：`codex/erp-scheduling-profit-20261011`。发布脚本：`deploy/erp-optimization-20261011-release.sh`。

## 发布前置要求

1. 服务器已有 0038 迁移、可工作的应用及识别 worker。已配置的学期、参与人和视觉模型不自动重设。
2. 当前代码是本次 SHA 的祖先，没有未提交的已跟踪修改，没有待迁移项。脚本发现不同历史、模式/依赖变化时停止，不强行覆盖。
3. 使用既有本地 PostgreSQL 与应用角色。脚本验证本地数据库范围，先暂停 Web/worker，创建私有数据库备份并验证目录可读取。
4. 仅当策略表缺少应用所需的 SELECT/INSERT/UPDATE/DELETE 权限时补齐；记录可逆 SQL，不变更 owner、角色管理权限或其他表。现有异常策略数据必须停止并私下核查，不把它改成默认策略。

## 阿里云 root 终端执行模板

将 `REVIEWED_FULL_SHA` 替换为本次交付的完整提交号。不要仅使用分支最新 HEAD 作为未经核对的发布目标。

```bash
bash --noprofile --norc <<'BASH'
set -Eeuo pipefail
set +x
umask 077
app=/opt/dongbo/app
sha=REVIEWED_FULL_SHA
branch=codex/erp-scheduling-profit-20261011
git -C "$app" fetch origin "$branch"
test "$(git -C "$app" rev-parse FETCH_HEAD)" = "$sha"
script=$(mktemp /tmp/dongbo-optimization-20261011-XXXXXXXX.sh)
log=$(mktemp /tmp/dongbo-optimization-20261011-XXXXXXXX.log)
git -C "$app" show "$sha:deploy/erp-optimization-20261011-release.sh" > "$script"
bash -n "$script"
printf '部署日志：%s\n' "$log"
bash "$script" "$sha" 2>&1 | tee "$log"
BASH
```

成功标志：`ERP OPTIMIZATION VERIFIED AT LOCAL NGINX ORIGIN`、正确 SHA、备份目录。这个标志表示源站验证成功，不等于公网 CDN、真实登录账号或视觉识别验收。

## 发布验证

- 脚本验证策略表权限及现有策略完整序列化，不输出策略配置值；校验原有排班迁移已应用。
- 检查服务账号能读运行文件、应用/worker active、健康接口 JSON、七个前端资源源站 hash。
- 浏览器 Ctrl+F5：确认侧栏文字、学期空态/实际班表、策略列表加载与重试、输入后重新计算、保存利润方案及历史版本。
- 未配置学期时由超级管理员通过“学期与识别设置”完成，不猜开学日期、不伪造全员无课。

## 回滚

发布失败由脚本回滚到备份的旧 SHA、重建前端并验证服务及资源；不倒退迁移、不恢复整库、不删除原图或利润方案。若输出 `ROLLBACK NOT VERIFIED`，停止重跑并检查日志和服务状态。

成功发布后的手动代码回滚也只允许备份中的精确旧 SHA，先核对代码没有后续变更，再在 umask 022 子进程内切换/重建；不使用 reset --hard。此动作需要另行确认当前服务器事实。

策略表补充的权限默认保留，因为旧代码仍需正常访问策略。若安全审计要求撤销，备份中的 `revoke-new-strategy-rights.sql` 只包含本次新增权限；核对影响后才由数据库管理员执行，不自动撤销或恢复数据库。

## 尚未在本次执行

没有连接生产服务器执行发布。公网缓存、真实视觉供应商、生产私有文件访问及备份实际恢复仍需现场验证；本地/模拟测试不得替代这些结论。
