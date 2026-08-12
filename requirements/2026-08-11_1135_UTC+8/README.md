# ERP PR #12 验收失败补漏包

- 需求编号：`ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-FIX-01`
- 补漏确认时间：**2026-08-11 11:35（UTC+8）**
- 被验收实施 PR：`#12`
- 被验收实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 被验收当前 HEAD：`d47fed21f2f45d747f87d6c4efc45b3e93020aa3`
- 本补漏文档分支：`docs/erp-replenishment-intransit-store-fix-20260811-1135`
- 本补漏目录：`requirements/2026-08-11_1135_UTC+8/`

## 结论

PR #12 **不得视为已完成版本**。代码虽然加入了部分字段和后端逻辑，但仍缺少多项已确认业务流程，并存在会造成库存/补货数据错误或 HTTP 500 的明确问题。

本目录文件：

1. `ERP_PR12_REMEDIATION_REQUIREMENTS.md`：逐项缺陷、修复要求与验收场景。
2. `CODEX_FIX_PROMPT.md`：直接交给 Codex 的第二轮修复提示词。
3. `PRODUCTION_VERIFICATION.md`：修复后上线前后的只读验证与故障定位要求。

## 执行边界

- Codex 必须在 PR #12 当前实施分支上继续修，不得从旧 `main` 重做。
- 不得删除已完成且正确的 3/7/15/30 加权销量算法、安全库存、波动、MOQ、pack 等既有逻辑。
- 不得自动 merge，不得直接部署生产。
- 修复后必须重新运行完整后端/前端测试，并给出新的最终 40 位 SHA。
