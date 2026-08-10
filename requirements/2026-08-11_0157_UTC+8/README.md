# ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-01

- 需求上传时间：**2026-08-11 01:57（UTC+8）**
- 仓库：`kevindongbo/codex`
- 需求文档分支：`docs/erp-replenishment-intransit-store-20260811-0157`
- 文件夹：`requirements/2026-08-11_0157_UTC+8/`
- 代码审计证据基线：`main` @ `3353edaaa4dce8ca44e8da729f22e3800aafa570`
- Codex 实际实施继承基线：`codex/implement-profit-strategy-ui-fixes-20260805` @ `63cad114ef9567ad40a1c9001b81261fedf830cc`（当前 Draft PR #10 HEAD）
- 建议 Codex 实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 实施 PR 目标分支：`codex/implement-profit-strategy-ui-fixes-20260805`

## 文件

1. `ERP_REPLENISHMENT_INTRANSIT_STORE_REQUIREMENTS.md`：完整业务需求、当前代码审计、迁移、API/UI、并发/审计和验收标准。
2. `CODEX_PROMPT.md`：可直接复制给 Codex 的实施提示词。
3. `DEPLOYMENT_HANDOFF.md`：Codex 完成代码后必须提供的真实部署信息，用于随后生成阿里云黑框执行命令。

## 边界

- 本分支只固化需求，不修改业务代码。
- 实际实施不得从旧 `main` 重新开始而丢失 PR #10 继承链上的已有功能。
- 不自动 merge，不直接部署生产。
- 阿里云命令必须在代码完成后，以**最终精确 HEAD SHA、真实 migration、实际服务/静态文件变化**生成，不能现在提前写死。

## 交付流程

1. 将 `CODEX_PROMPT.md` 交给 Codex。
2. Codex 从指定实施基线创建实施分支并修改代码。
3. Codex生成 migration、补测试并执行完整测试。
4. Codex 将修改后的代码推送到 GitHub，并创建 Draft PR。
5. Codex 返回最终 HEAD SHA、migration、测试结果、部署影响与回滚影响。
6. 将 Codex 最终结果发回 ChatGPT。
7. ChatGPT 再按最终 SHA 给出阿里云黑框可复制执行的：备份 → checkout 精确 SHA → 迁移 → build/collectstatic → 重启 → health check → smoke test → 回滚命令。