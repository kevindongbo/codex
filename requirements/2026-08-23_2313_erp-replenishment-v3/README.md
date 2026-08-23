# ERP 智能补货 V3 + 调拨异常关闭需求包

- 原需求上传时间：2026-08-23 23:13 +08:00
- 详细版覆盖更新时间：2026-08-23 23:26 +08:00
- 需求版本：V3 Detailed Revision 1
- 需求分支：`requirements/erp-replenishment-v3-20260823-2313`
- 开发基线：`codex/erp-analytics-profit-creator-workflow-20260820`
- 代码实现分支：`codex/erp-replenishment-v3-implementation-20260823`
- 仓库：`kevindongbo/codex`

## 本次覆盖说明

2026-08-23 23:26 +08:00 将此前的压缩版需求直接替换为完整详细版。业务规则、公式、示例、边界条件、迁移要求和验收测试均按已确认内容完整保留。

此前的 `REQUIREMENTS.md`、`CODEX_PROMPT.md`、`HANDOFF_CHECKLIST.md` 将由以下编号文件取代，不再作为开发真值。

## 文件结构

1. `01_FULL_REQUIREMENTS.md`：完整详细业务需求，**最高优先级、最终业务真值**。
2. `02_CURRENT_CODE_AUDIT.md`：当前代码与新需求差异，帮助 Codex 定位改动。
3. `03_ACCEPTANCE_TESTS.md`：数字案例、测试场景、完整验收标准。
4. `04_CODEX_PROMPT.md`：可以直接交给 Codex 的执行提示词。
5. `05_HANDOFF_CHECKLIST.md`：Codex push GitHub 后给部署阶段的交接清单。

## Codex 使用方式

Codex 开发前必须从需求分支完整读取本目录全部编号文件，再切换到实现分支开发。不要直接修改 `main`，不要在需求分支写业务代码。

如文件之间出现表述冲突，以 `01_FULL_REQUIREMENTS.md` 为准。
