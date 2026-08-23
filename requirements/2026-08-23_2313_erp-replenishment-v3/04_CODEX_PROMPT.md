# Codex 执行提示词

> 详细版覆盖更新时间：2026-08-23 23:26 +08:00

处理 GitHub 仓库：`kevindongbo/codex`。

- 开发基线：`codex/erp-analytics-profit-creator-workflow-20260820`
- 需求分支：`requirements/erp-replenishment-v3-20260823-2313`
- 实现分支：`codex/erp-replenishment-v3-implementation-20260823`
- 需求目录：`requirements/2026-08-23_2313_erp-replenishment-v3/`

开始修改代码前，必须从需求分支完整读取：

1. `README.md`
2. `01_FULL_REQUIREMENTS.md`
3. `02_CURRENT_CODE_AUDIT.md`
4. `03_ACCEPTANCE_TESTS.md`
5. `05_HANDOFF_CHECKLIST.md`

其中 `01_FULL_REQUIREMENTS.md` 是本次业务真值。不得因为需求较长而自行压缩、改写已确认公式或省略边界条件。

然后：

1. fetch 最新 refs，确认实现分支与开发基线关系；不要强制 reset 别人的提交。
2. 重新审计现有 models / serializers / views / replenishment / migrations / tests / `team.js` / `app.js` / 采购 / 调拨 / ledger / scheduler。
3. 按需求实施后端、前端、migration 和测试修改；后端必须是补货计算真值。
4. 严格执行 `03_ACCEPTANCE_TESTS.md`，记录通过、失败、跳过。
5. 不直接修改 `main`，也不在需求分支写业务代码。
6. 完成后 commit 并 push 到 `codex/erp-replenishment-v3-implementation-20260823`，不能只留在本地。
7. 最终按 `05_HANDOFF_CHECKLIST.md` 回传：最终 commit SHA、修改文件、migration、测试结果、依赖/环境变量/定时任务/服务重启、已知风险、未完成项和回滚方法。

特别禁止：

- 通过删除后端 `idempotency_key` 校验修复调拨异常关闭；
- 把全仓加权公式改成“各窗口日均再加权”；
- 硬编码 9.3；
- 继续让客户退货扣减历史需求；
- 在 V3 目标库存里偷偷叠加旧 safety margin / volatility / service level；
- 批量修改时覆盖用户未选择修改的字段。
