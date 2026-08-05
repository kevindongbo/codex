# ERP 利润策略界面修正需求包

- 需求编号：`ERP-PROFIT-UI-REQ-20260805-01`
- 确认时间：2026-08-05 17:43（UTC+8）
- 审计仓库：`kevindongbo/codex`
- 审计基线分支：`codex/implement-profit-settlement-strategies-20260805`
- 审计基线 SHA：`807f207b35a7ea0b5b0b7448627146af4a58f852`
- 文档分支：`docs/profit-strategy-ui-fixes-20260805-1743`
- 建议实施分支：`codex/implement-profit-strategy-ui-fixes-20260805`

## 文件

1. `PROFIT_STRATEGY_UI_REQUIREMENTS.md`：代码审计、最终交互口径、接口与验收标准。
2. `CODEX_PROMPT.md`：可直接交给 Codex 的实施提示词。
3. `DEPLOYMENT_HANDOFF.md`：代码完成后更新阿里云部署文档的交接规则。

## 执行顺序

1. Codex 从审计基线创建建议实施分支。
2. 先审计当前实现，再按需求修改前端、后端、测试与部署文档。
3. 实际运行测试并记录真实结果。
4. 推送代码并创建 Draft PR，base 为审计基线分支。
5. 不自动合并，不直接部署生产。
6. 新代码最终 SHA 确定后，更新阿里云部署、验证和回滚命令。
