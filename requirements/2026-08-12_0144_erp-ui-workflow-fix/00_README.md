# ERP 工作流修复需求交接

- 需求编号：`ERP-UI-WORKFLOW-FIX-20260812-0144`
- 需求上传时间：`2026-08-12 01:44 UTC+8`
- GitHub 仓库：`kevindongbo/codex`
- 需求分支：`codex/erp-ui-workflow-fix-20260812-0144`
- 基线分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 基线 HEAD：`5b86a1192a2cabbfa564de9e842aa39d93bd87fa`
- 目标：由 Codex 在本需求分支上完成代码修改、测试并 push，不直接改生产服务器。

## 文件说明

- `00_README.md`：本次需求的时间、分支、执行流程。
- `01_REQUIREMENTS.md`：完整业务需求、现状审计、验收标准。
- `02_CODEX_PROMPT.md`：可以直接复制给 Codex 的执行提示词。
- `03_ALIYUN_DEPLOY_TEMPLATE.md`：Codex 完成并 push 后的阿里云部署模板；正式执行前必须用 Codex 最终 SHA 替换占位符。

## Codex 工作规则

1. 开工前先执行 `git status --short`、`git branch -vv`、`git log --oneline --decorate -20`、`git reflog -20`，防止覆盖尚未 push 的本地工作。
2. 必须切到本分支：`codex/erp-ui-workflow-fix-20260812-0144`。
3. 优先修复现有实现，不允许重复创建 Store、StockTransfer、StockTransferPackage、订单选仓等第二套业务模型。
4. 修改后必须运行后端、前端现有测试，并新增本需求回归测试。
5. 全部通过后 push 到同一需求分支。
6. Codex 最终必须输出：分支、最终 HEAD SHA、修改文件、migration、测试结果、已知剩余问题、部署影响、回滚影响。
7. 不自动 merge 到 main，不自动部署生产。

## 本轮范围

只处理以下五类问题：

1. 利润试算当前配置刷新丢失。
2. 订单选择仓库仍要求人工输入 UUID。
3. ERP 订单取消当前实际不可用/无有效结果。
4. 库存列表缺少在途库存，仓间调拨物流没有完整接通。
5. 店铺保存成功后列表仍显示为空。

不得把本轮扩大成 ERP 全面重构。