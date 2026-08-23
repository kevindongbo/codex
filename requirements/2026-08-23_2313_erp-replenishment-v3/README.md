# ERP 智能补货 V3 + 调拨异常关闭需求包

- 需求上传时间：2026-08-23 23:13 +08:00
- 需求分支：`requirements/erp-replenishment-v3-20260823-2313`
- 开发基线：`codex/erp-analytics-profit-creator-workflow-20260820`
- 预留实现分支：`codex/erp-replenishment-v3-implementation-20260823`
- 仓库：`kevindongbo/codex`

## 文件

1. `REQUIREMENTS.md`：完整业务规则、公式、数据模型、UI、迁移、测试和验收标准。
2. `CODEX_PROMPT.md`：可直接交给 Codex 的执行提示词。
3. `HANDOFF_CHECKLIST.md`：Codex 修改完成后必须回传的 GitHub 信息，以及后续阿里云部署前的交接清单。

## 使用方式

Codex 开始开发前先读取本文件夹全部文件，再从开发基线创建/切换到实现分支。不得直接修改主分支，不得把需求分支当成生产分支。

需求文档是本次修改的业务真值；若现有代码与文档冲突，以 `REQUIREMENTS.md` 为准，但应优先做最小兼容修改并保留历史数据。