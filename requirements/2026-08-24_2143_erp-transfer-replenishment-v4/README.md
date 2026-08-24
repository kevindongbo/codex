# ERP 仓间调拨 + 智能补货 V4 需求包

- 需求包上传时间：**2026-08-24 21:43 +08:00**
- 仓库：`kevindongbo/codex`
- 独立需求分支：`requirements/erp-transfer-replenishment-v4-20260824-2143`
- 独立 Codex 实现分支：`codex/erp-transfer-replenishment-v4-implementation-20260824`
- Codex 实现基线：`codex/erp-replenishment-v3-implementation-20260823`
- 实现基线 HEAD：`26083e6146ea2717d376065857045089d8b4e6aa`
- 旧 V3 需求上传：2026-08-23 23:13 +08:00；详细版覆盖：2026-08-23 23:26 +08:00

> 本目录是本轮开发的需求入口。禁止修改 `main`。禁止把需求分支当实现分支。禁止为了缩短上下文而省略或改写关键业务公式、库存语义、幂等规则和验收边界。

## 阅读顺序与优先级

1. `01_INHERITED_V3_FULL_REQUIREMENTS.md`：上一版完整 V3 业务规则，原文完整保留，不压缩。
2. `02_V4_CURRENT_REQUIREMENTS_AND_OVERRIDES.md`：2026-08-24 最新用户要求。仅在与 V3 明确冲突时覆盖 V3；其余 V3 条款全部继续生效。
3. `03_CURRENT_CODE_AUDIT_2026-08-24.md`：对当前实际实现基线 `26083e...` 的代码审计，不是业务真值。
4. `04_INHERITED_V3_ACCEPTANCE_TESTS.md`：V3 原验收测试，完整保留。
5. `05_V4_ACCEPTANCE_AND_REGRESSION_TESTS.md`：本轮新增/修正验收项。
6. `06_CODEX_IMPLEMENTATION_PROMPT.md`：给 Codex 的执行提示词。
7. `07_HANDOFF_CHECKLIST.md`：Codex 完成后必须返回的交接信息。
8. `08_REQUIREMENT_TRACEABILITY.md`：需求 → 代码 → 测试追踪表。

## 最终业务真值的判定

- V4 没有明确修改的内容：继续执行 V3。
- V4 明确修改的内容：以 V4 为准。
- 代码当前怎么写，不代表业务规则正确；如果代码与上述需求冲突，必须改代码。
- 单元测试通过不代表页面完成；用户已经提供真实页面截图和真实点击错误，必须做浏览器级验收。

## 本轮明确不做

- 不改 `main`。
- 不自动 merge PR。
- 不直接部署生产。
- 不新建第二套重复的库存、调拨或补货模型。
- 不删除或静默改写历史库存流水、采购、调拨、推荐快照或审计记录。
- 不通过删测试、弱化断言、硬编码数字来制造“通过”。

## 当前最重要的四组问题

1. 调拨异常关闭原因必须可空，同时保留强幂等；结束调拨的剩余异常结案原因也按同一可选规则处理。
2. 调拨商品明细必须真正可展开，并统一显示商品图片、名称、SKU、数量。
3. 智能补货主表字段和位置必须重排，新增“近30天出库来源”，“查看周期明细”归属该字段；业务口径继续使用 V3 的真实销售出库、不扣退货规则。
4. 智能补货全部按钮必须真实可点击，修复 `Cannot set properties of null (setting 'value')` 等运行时错误，并做真实浏览器回归。
