# ERP-REPLENISHMENT-INTRANSIT-STORE-20260811 部署交接

本次仅完成代码与迁移，Codex 未连接阿里云、未执行生产部署。以下事实来自仓库与需求交接文件。

- 实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 最终 SHA：`9b9c791a8f7b420876b8a4f09e3335ca6c6d0f3a`
- Draft PR：[#12](https://github.com/kevindongbo/codex/pull/12)
- 新增迁移：`backend/apps/erp/migrations/0028_replenishment_intransit_store.py`、`0029_sales_order_external_sku.py`
- `0028` 包含数据迁移：仓库默认周期回填、策略 coverage 回填、历史采购批次确认标记、旧调拨在途余额及兼容包回填。
- 数据迁移可能不可逆；回滚前必须保留 PostgreSQL 备份，不建议直接 reverse migration。
- 前端静态文件未在本轮修改；如部署仓库既有前端构建流程要求，按仓库现行流程执行。
- 未新增环境变量、Docker、Nginx、systemd 配置；本文件不猜测生产目录、数据库名、账号或服务名。
- 生产部署命令：本轮不提供可执行生产命令，待最终 SHA、服务器真实配置由运维确认后生成。
- 回滚影响：代码可回退至部署前 SHA；已产生的新业务数据和迁移结构需使用备份恢复或人工数据迁移，不能仅 checkout 代码。

部署前必须完成：只读检查、记录当前 SHA、PostgreSQL 备份、精确 SHA 检出、迁移、必要的构建/静态收集、服务重启、Nginx 检查、健康检查和日志检查。
