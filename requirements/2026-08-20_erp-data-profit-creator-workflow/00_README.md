# ERP 数据分析、调拨收口、利润记录与达人管家需求包

需求日期：2026-08-20（Asia/Shanghai）

GitHub 仓库：`kevindongbo/codex`

代码审计基线：

- 分支：`codex/erp-production-regression-fix-20260813`
- Commit：`eebdbfcbf033c74f8f2d82e8204336c08834c394`
- Draft PR：<https://github.com/kevindongbo/codex/pull/15>

建议实施分支：`codex/erp-analytics-profit-creator-workflow-20260820`

本目录包含：

- `00_README.md`：基线、范围和执行顺序。
- `01_REQUIREMENTS.md`：最终业务需求、数据口径与验收标准。
- `02_CODEX_PROMPT.md`：可直接交给 Codex 的实施提示词。

## 执行顺序

1. 完整阅读项目记忆、`AGENTS.md`、相关 `agent-memory`、既有需求以及本目录全部文件。
2. 核对本地工作区、GitHub 分支和 PR 的当前状态；实际状态优先于本文记录。
3. 从已部署基线或其最新后继提交创建新的 `codex/` 功能分支，不在 `main` 或 PR #15 的分支上直接叠加开发。
4. 先补回归测试，再按 `01_REQUIREMENTS.md` 实施。
5. 数据库变更必须包含 migration、备份、验证和回滚说明。
6. 完成后只暂存本次相关文件，提交、推送并创建 Draft PR；不得自动合并或部署生产。

## 范围说明

本次包含七组需求：

1. 部分收货调拨的明确结束与在途归零。
2. 智能补货表头固定及商品列对齐。
3. 各仓库近 7 天出库明细。
4. 将竞品监控升级为数据分析模块。
5. 广告返点、真实 ROI/CPA 及利润配置持久化修复。
6. 新增达人管家。
7. 新增商品利润表和可重算的版本化试算记录。

`01_REQUIREMENTS.md` 是本次最终业务验收标准。
