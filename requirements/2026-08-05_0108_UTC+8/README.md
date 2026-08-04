# 利润测算、结算口径与采购在途 UI 需求包

- 需求编号：`ERP-PROFIT-REQ-20260805-01`
- 需求确认时间：2026-08-05 00:42（UTC+8）
- GitHub 上传时间：2026-08-05 01:08（UTC+8）
- 仓库：`kevindongbo/codex`
- 文档分支：`docs/profit-calculator-requirements-20260805-0108`
- 代码审计基线：`codex/implement-erp-requirements-20260804`
- 计划代码分支：`codex/implement-profit-settlement-strategies-20260805`

## 文件说明

- `PROFIT_CALCULATOR_REQUIREMENTS.md`：完整需求、计算口径、数据模型、接口、前端与验收标准。
- `CODEX_PROMPT.md`：可直接交给 Codex 的执行提示词。
- `DEPLOYMENT_HANDOFF.md`：代码完成后生成阿里云黑框命令的交接规则。

## 执行顺序

1. Codex 从代码审计基线创建计划代码分支。
2. Codex 按需求修改代码、生成迁移并运行真实测试。
3. Codex 将修改后的代码推送到 GitHub，并创建 Draft PR。
4. Codex 在 PR 中写明最终精确提交 SHA、测试结果、迁移和回滚风险。
5. 不自动合并，不直接部署生产。
6. 待代码 PR 和最终 SHA 确定后，再生成可直接粘贴到阿里云黑色终端的部署、验证及回滚命令。

## 边界

- 真实 TikTok 结算单只用于校验预测公式，不作为系统持续输入。
- 不实现“实际手续费覆盖预测手续费”。
- 不改变多商品采购订单现有展开样式。
- 不借本需求修改竞品、库存、补货、店铺等无关模块。
