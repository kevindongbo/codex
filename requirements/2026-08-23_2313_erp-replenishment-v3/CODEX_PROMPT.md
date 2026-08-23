# Codex 执行提示词

> 需求上传时间：2026-08-23 23:13 +08:00

你现在要在 GitHub 仓库 `kevindongbo/codex` 中实现一次 ERP 修改。

## 1. 分支与文档

开发基线：

`codex/erp-analytics-profit-creator-workflow-20260820`

需求分支：

`requirements/erp-replenishment-v3-20260823-2313`

需求目录：

`requirements/2026-08-23_2313_erp-replenishment-v3/`

完整业务真值：

`requirements/2026-08-23_2313_erp-replenishment-v3/REQUIREMENTS.md`

预留实现分支：

`codex/erp-replenishment-v3-implementation-20260823`

先 fetch 最新 refs，读取需求分支中的 README、REQUIREMENTS、HANDOFF_CHECKLIST，再切换到实现分支开发。不要直接修改 `main`，不要直接在需求分支写业务代码。

如果预留实现分支已存在，先确认它没有额外业务提交；它应从开发基线创建。若发现实现分支已经有其他人的新提交，不要强制 reset，先说明冲突并采用安全方式继续。

## 2. 工作方式

不要只改前端显示。先审计：

- `backend/apps/erp/models.py`
- `backend/apps/erp/serializers.py`
- `backend/apps/erp/views.py`
- `backend/apps/erp/replenishment.py`
- ERP migrations
- ERP tests
- `team.js`
- `app.js`
- 与 replenishment / stock-transfer / purchase / ledger / scheduler 相关的其他文件

优先复用已有模型、流水、采购、调拨、P80 到货周期和任务机制。

后端必须是计算真值；不要在前端留下与后端不同的补货公式。如果本地模式确实必须保留 fallback，应与后端公式完全一致，并有测试。

## 3. 必须完成的核心修改

### A. 调拨运输异常关闭 Bug

修复 `closeTransferException()` 缺少 `idempotency_key`。

必须沿用现有幂等模式，不允许通过把后端字段改成非必填来绕过。

异常关闭后的业务语义保持：来源仓不恢复、目标仓不增加、在途清零、异常数量和原因保留、重复请求不产生二次库存影响。

### B. 智能补货 V3

严格以 `REQUIREMENTS.md` 为准实现，尤其注意以下不可误解规则：

1. 页面仍按仓库查看。
2. 需求侧统计全仓，库存侧只使用 SKU 主力仓。
3. 需求只计 `SHIPMENT + MANUAL_OUTBOUND`，客户退货不扣历史需求。
4. 强制加权公式：

`(Q3*W3 + Q7*W7 + Q15*W15 + Q30*W30) / (3*W3 + 7*W7 + 15*W15 + 30*W30)`

禁止先把各窗口除天数再加权；禁止硬编码 9.3。

5. 权重支持全局默认 + SKU override，四项必须严格合计 100%，支持恢复全局。
6. 每 SKU 可设置一个主力仓，支持单个、多选、全选批量设置。
7. 有主力仓时 SKU 只出现在主力仓页；无主力仓时所有仓页可见，但最迟下单/建议补货/紧急度显示“请先设置主力仓库”。
8. 主力仓切换后 SKU 自身权重、目标覆盖、安全库存、起订量、整箱数保持不变。
9. 可售天数只用主力仓可用库存，不包含在途。
10. 触发和建议补货库存位使用主力仓可用 + 已确认采购在途 + 已确认调拨在途。
11. 到货周期优先级：完整收货历史 P80 → 首次收货 P80 → 人工 fallback → 系统 fallback。
12. 目标覆盖默认 30，可修改，可清空。
13. 目标覆盖有值：`target=max(lead,coverage)*daily`，不叠加任何安全库存/波动/安全余量。
14. 目标覆盖有值时触发点：`daily*lead`。
15. 目标覆盖为空时：`target=trigger=daily*lead+SKU固定安全库存`。
16. 未触发时建议补货必须为 0 / 暂不补货。
17. 触发后基础建议：`max(target_inventory-inventory_position,0)`。
18. UI 文案只使用“起订量”，不出现 MOQ。
19. 起订量和整箱数都允许为空；只有设置时才修正数量。
20. 起订量先应用，整箱数后向上取整。
21. 最迟下单只按库存位耗尽日期减 lead，不再减 safety/review 等额外天数。
22. 删除用户可编辑复核周期；后台每天自动检查一次，同时关键事件实时重算/失效。
23. 主表 checkbox 列缩窄、商品列左移，标题改为“全仓加权日均出库”。
24. 新增“近30天出库来源”，主表只显示合计，详情用 Popover/Modal，不撑高表格行。

## 4. 数据模型与 migration

先审计现有 `SKU.safety_stock`、`ReplenishmentPolicy`、`ReplenishmentSettings` 和历史 migrations。

选择迁移风险最低的方式实现 SKU 级补货策略。可以新增 `SKUReplenishmentProfile` 或采取等价安全方案，但不要继续让同一个 SKU 因仓库不同保存多套应当相同的 SKU 参数。

以下必须能够为 SKU 级配置：

- 主力仓
- SKU 权重 override
- 目标覆盖天数
- 固定安全库存
- 人工 lead fallback
- 起订量
- 整箱数

`起订量`、`整箱数` 需要真正支持 null/blank。旧系统默认 1 应按需求文档制定安全 migration；不要直接破坏历史数据。

旧 `safety_days/review_cycle_days/service_level_factor/safety_margin_ratio/volatility` 不要求本次删除数据库字段，但 V3 最终计算不得再偷偷使用它们。

## 5. 测试

必须新增/更新自动化测试，至少完整覆盖 `REQUIREMENTS.md` 的 Case A-N 和调拨异常关闭测试。

还应补前端测试/可测试断言，确认：

- close exception 请求包含幂等键；
- 批量 patch 不覆盖未选择字段；
- 权重合计校验；
- 未设置主力仓的页面状态；
- 起订量/整箱数可空；
- 主表不再行内展开长详情。

运行仓库现有适用测试。不要只报告“代码看起来正确”。

## 6. 提交和上传 GitHub

完成后把所有代码、migration、测试提交到：

`codex/erp-replenishment-v3-implementation-20260823`

不要直接 push 到 main。

提交信息应能看懂本次内容，例如：

`feat(erp): implement replenishment v3 and fix transfer exception idempotency`

如果变更较大，可以拆成多个有意义的 commits，但最终必须全部 push。

## 7. 完成后给出的报告

最终回复必须严格提供：

1. 实现分支名。
2. 最终 commit SHA。
3. 所有修改文件列表。
4. 新增 migration 文件名和作用。
5. 测试命令。
6. 每组测试的结果（通过/失败/跳过数量）。
7. 如果有失败或没跑的测试，明确说明原因，不得隐藏。
8. 是否新增/修改定时任务、worker、cron、Celery 或管理命令。
9. 生产部署是否必须运行 `python manage.py migrate`。
10. 是否需要 `collectstatic` / 前端构建。
11. 是否需要重启 gunicorn/uwsgi/celery/nginx/其他服务。
12. 新增环境变量或配置项（如果没有，写“无”）。
13. 从开发基线到实现分支的 diff 摘要。
14. 仍未完成或与需求文档有差异的条目；完全没有则写“无”。
15. 推荐的回滚 commit / 回滚方法。

不要给泛化部署命令。部署命令将在拿到你的最终 commit SHA 和实际项目运行方式后，由上层再生成阿里云终端的精确命令。