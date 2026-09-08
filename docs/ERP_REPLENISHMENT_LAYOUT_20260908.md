# 智能补货布局修复（2026-09-08）

## 范围

- 批量参数窗口的主力仓库选项仅显示当前仓库；未勾选覆盖字段仍保持原设置。提交时检查窗口仓库和当前仓库一致，阻止过期窗口或被篡改的下拉值。本次是批量界面的约束，不修改单 SKU 配置接口的既有权限规则。
- 保留十一列既有业务顺序，商品标题左对齐，其余业务列居中；粘性克隆继承原表样式和实测列宽。
- 近30天来源数量在上、明细按钮在下。修复推荐响应读取不存在的 quantity 字段：优先使用后端 true_outbound，兼容 quantity，不在前端计算销量。
- 静态资源版本提升为 `20260908-replenishment-layout-1`。
- 不修改补货公式、库存流水、采购/调拨状态机、数据库或生产环境。

## 实际验证

- `python backend/manage.py check`：通过。
- `python backend/manage.py makemigrations --check --dry-run`：No changes detected。
- `python backend/manage.py test apps.erp.tests --noinput`：171/171，通过；使用隔离 SQLite 内存数据库与临时测试加密密钥，非生产 PostgreSQL。
- `node --check app.js`、`node --check team.js`：通过。
- `node scripts/build-site.mjs`：通过。
- `node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs`：60/60，通过。首次在重新 build 前执行，资源版本测试失败；重新构建后全通过。
- `node tests/browser/replenishment-sticky.test.mjs`：真实 Edge/Playwright，本地固定 API 数据；勾选 SKU、打开批量窗口、验证只有本仓选项、取消；真实 true_outbound=60 显示60件且按钮在下；1440×900、1920×1080、横向滚动后11列表头边界误差不超过2px；pageerror=0、console.error=0。
- `node tests/browser/erp-usability.test.mjs`：18个模块/视口组合、无页面溢出、弹窗焦点循环及恢复，通过。
- `node tests/browser/profit-workflow.test.mjs`：利润配置、保存/重开/重算流程，通过。
- `node --test tests/deploy-permissions.test.mjs`：2/2，通过，包含 Bash 语法及权限隔离。
- `git diff --check`：通过。

## 发布与边界

沿用功能分支 `codex/erp-usability-audit-20260906` 和 Draft PR #19，不 merge main、不直接部署。Git HTTPS 连接重置时使用 GitHub Contents API 发布，最终核验远端完整 tree 与本地提交 tree 一致；本地 SHA 与远端 SHA 可不同。

无需 migrate、collectstatic、新依赖、环境变量或定时任务。部署需要 build 并重启现有 dongbo-erp.service，沿用已修复权限掩码的 `deploy/erp-usability-release.sh`。回滚应使用发布备份中的 previous-sha 和原有受保护流程，不恢复数据库。公网 CDN、生产登录状态和真实业务数据验收：未验证。
