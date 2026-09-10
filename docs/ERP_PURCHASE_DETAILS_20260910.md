# 采购明细折叠与表头对齐

本轮基线：c1dd7e0ffbd2234edc7457d9ad25007efe428b71。
实现分支：codex/erp-usability-audit-20260906；关联 PR #19。

## 用户最新口径

- 恢复商品明细列，不恢复采购／已收列。
- 单 SKU 保留图片、名称、SKU，不在商品列重复数量。
- 多 SKU 默认首项商品摘要与展开入口；数量仅在展开的全部明细内显示。
- 展开数量沿用采购行 orderedQty，不改为在途或重算库存。
- 保留国内／国际物流单号、相同国际单号集中排列、单号可空与主力仓切换。
- 十列表头与数据行共享列宽，文字与数值分别统一对齐；窄屏表格内部横向滚动。

## 修改文件

app.js、index.html、styles.css、tests/site.test.mjs、tests/browser/purchase-primary.test.mjs、本报告。

## 实际验证

- `node --check app.js`、`node --check team.js`：通过。
- `node scripts/build-site.mjs`：通过。
- `node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs`：63/63。
- `python backend/manage.py check`：通过。
- `python backend/manage.py makemigrations --check --dry-run`：No changes detected。
- `python backend/manage.py test apps.erp.tests --noinput`：175/175（本地 SQLite）。
- `node tests/browser/purchase-primary.test.mjs`：真实 Edge 点击展开／收起；单 SKU 无数量；1440×900、1920×1080 展开与收起、滚动前后十列表头/单元格 X 坐标与宽度误差不超过 1px；物流保存、分组、主力仓回归通过。pageerror=0，console.error=0。
- `node tests/browser/replenishment-sticky.test.mjs`：两种尺寸通过。
- `node tests/browser/erp-usability.test.mjs`：18 种模块/视口组合及焦点回归通过。
- 首次前端测试因先测后构建读取上轮 dist，资源版本断言失败；重新构建后完整 63 项通过，未弱化断言。

## 部署与回滚

本轮无新增 migration、依赖、环境变量或定时任务；无后端业务修改。
沿用 deploy/erp-usability-release.sh，需前端 build；不需要 collectstatic。
若服务器还未应用上一轮 0037，既有发布脚本将备份数据库并应用/核验该迁移。
部署会短暂重启 dongbo-erp.service；不直接部署生产、不合并 main。
回滚到部署备份记录的 previous-sha.txt 对应代码并构建、重启、验健康；保留已应用 0037 和物流数据，不反向迁移或还原整库。
生产 PostgreSQL、公网 CDN 和登录后业务验收：未验证，需用户部署后检查。
