# ERP-REPLENISHMENT-INTRANSIT-STORE-20260811 部署交接

本轮仅完成代码、迁移和本地验证；Codex 未连接阿里云，也未执行生产部署。

- 实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 已完整测试的实施 SHA：`2377dfb874767b24fa0bb318ff0efe05dfe3da0a`
- Draft PR：[#12](https://github.com/kevindongbo/codex/pull/12)
- 新增迁移：`0028_replenishment_intransit_store.py`、`0029_sales_order_external_sku.py`
- `0028` 包含 Data Migration：回填仓库默认周期、SKU 策略覆盖周期、历史采购批次确认标记、旧调拨在途余额及兼容包。
- Data Migration 不保证安全反向执行；生产迁移前必须备份 PostgreSQL，回滚时按数据影响决定是否恢复备份。
- 修改了静态前端 `app.js`，生产更新需要执行仓库既有前端构建流程。
- 已验证构建命令：`node scripts/build-site.mjs`。
- Django 静态资源仍应沿用生产现有 `collectstatic` 流程。
- 未新增环境变量、Docker、Nginx、systemd service/timer 配置。
- 无法仅从本轮需求确认生产目录、数据库账号、数据库名和服务名，因此本文不生成或猜测生产执行命令。

## 已执行测试

- `python manage.py makemigrations --check --dry-run`：通过，无待生成迁移。
- `python manage.py test apps.erp.tests --noinput`：通过，131 项全部成功。
- `node --check app.js`、`team.js`、`profit-calculator.js`：通过。
- `node --test tests/site.test.mjs`：15 项通过。
- `node --test tests/domain.test.mjs`：16 项通过。
- `node --test tests/team.test.mjs`：20 项通过。
- `node scripts/build-site.mjs`：通过，生成 `dist/server/index.js`。

## 部署与回滚影响

部署必须依次完成只读环境确认、记录部署前 SHA、数据库备份、检出上述精确测试 SHA、迁移、前端构建、静态收集、重启真实应用服务、Nginx 检查、健康检查和日志检查。

代码可回退到部署前 SHA；如果迁移后已经产生采购包、调拨包、补货推荐或未映射订单行等新业务数据，不能只回退代码，需人工评估并按备份恢复数据库。
