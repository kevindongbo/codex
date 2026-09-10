# 主力仓切换与采购物流拆分交付（2026-09-10）

## 当前需求覆盖

本次明确取代 2026-09-08 的“主力仓只选本仓”解释。单 SKU、批量参数均使用团队服务端仓库目录的真实 UUID，允许选择其他有权限仓库。后端已有组织/仓库权限不放宽；主力仓保存后只在新主力仓补货列表出现。安全库存留空保留 SKU 原值，明确输入 0 仍保存 0，不写 NULL。

采购主列表仅移除商品明细、采购/已收两个展示列；明细及收货数据仍保存在原模型和编辑/收货流程中。物流拆成国内、国际单号，可均为空，之后可补填。相同非空国际单号的采购单相邻展示，多单号采用关联分组，每张采购单仅显示一次，空单号不归为同一组，不合并单据或库存。

旧 tracking_number 原样保留并在列表注明“历史单号（未分类）”，不猜测归属；新字段包含在编辑审计快照中。修正本地演示采购编辑生成同 ID 副本的问题。后端补货公式、库存流水记账和锁库规则未变。

## 文件

- app.js / team.js / index.html：服务端仓库目录、空安全库存、采购列表、分组、包裹编辑/保存/收货选项、资源版本。
- backend/apps/erp/models.py / serializers.py / services.py / views.py：物流字段、空号输入、包裹归属校验、安全库存留空保留、审计。
- backend/apps/erp/migrations/0037_purchase_domestic_international_tracking.py：迁移。
- backend/apps/erp/tests/test_purchase_tracking_v2.py / test_purchase_tracking_migration.py / test_replenishment_input_safety.py：接口、迁移、主力仓变更测试。
- tests/team.test.mjs / site.test.mjs / browser/replenishment-sticky.test.mjs / browser/purchase-primary.test.mjs：适配器及实际浏览器回归。
- deploy/erp-usability-release.sh：仅允许本次0037变更，数据库备份、校验、短暂停服务、迁移及代码回滚保护。

## 迁移与回滚

0037 在现有 PurchaseShipment 增加 domestic_tracking_number、international_tracking_number（可空字符串，国际单号索引）。保留 legacy tracking_number，原唯一约束调整为只约束非空历史单号，允许多个未填单号包裹。新列具有数据库默认值，旧代码回滚后仍能插入记录。

反向迁移若发现新单号数据或同采购单多个空历史单号包裹，主动拒绝以防丢数据。推荐仅回滚应用至部署备份 previous-sha.txt 指定版本，保留0037和新物流数据；旧页面不展示新字段。不要 restore 数据库、fake 迁移或删除包裹。上线前备份，迁移完成后核验实际服务和公网界面。

## 实际测试

- Python manage.py check：通过。
- Python manage.py makemigrations --check --dry-run：No changes detected。
- Python manage.py test apps.erp.tests --noinput：175/175，通过，隔离 SQLite 测试数据库；包括0036→0037、旧代码插入兼容、拒绝丢数据回退、安全条件下回退与再次升级。
- node --check app.js / team.js：通过。
- node scripts/build-site.mjs：通过。
- node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs：62/62，通过。
- node --test tests/deploy-permissions.test.mjs：2/2，通过（Bash语法、部署/回滚权限掩码隔离；非真实服务器部署）。
- node tests/browser/purchase-primary.test.mjs：真实 Edge/Playwright，主力仓选择其他 UUID 并点击保存，空安全库存不提交NULL；本地采购空物流保存、补填两类单号、保存再打开、采购分组及移除列；pageerror=0、console.error=0。团队保存走真实适配器/模拟HTTP，采购页面保存为本地测试数据；后端实际 API 持久化另由 Django 测试验证。
- node tests/browser/replenishment-sticky.test.mjs：1440×900、1920×1080、横向滚动、11列表头坐标误差≤2px、批量选择其他仓，通过。
- node tests/browser/erp-usability.test.mjs：18个模块/视口组合与焦点回归，通过。
- node tests/browser/profit-workflow.test.mjs：通过。
- git diff --check：通过。

开发中浏览器首次失败分别暴露了模拟数据未包含后台读取接口、默认筛选排除草稿和本地编辑产生重复单据；补全测试夹具并修复实际编辑问题后重新运行通过，没有删除业务断言。

## 部署边界

需要 migrate、前端 build、重启 dongbo-erp.service。无需 collectstatic、新依赖、新环境变量、cron/Celery/定时任务改动。沿用当前功能分支 codex/erp-usability-audit-20260906，不 merge main，不直接生产部署。

生产 PostgreSQL 迁移及完整数据库恢复演练、公网 CDN 缓存、生产登录业务验收：未验证。PR #19 本轮状态查询遇到 GitHub 公共API限流；推送后以远端分支SHA核验代码交付，PR实时状态单独注明。
