# 阿里云部署交接要求（Codex 完成代码后填写）

- 需求编号：`ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-01`
- 需求上传时间：`2026-08-11 01:57（UTC+8）`
- 目的：本文件**不是现在执行部署**，而是让 Codex 在代码完成并推送 GitHub 后，提供生成阿里云黑框命令所需的真实事实。

## Codex 完成后必须提供

1. 最终实施分支名称。
2. 最终精确 HEAD SHA（40 位）。
3. Draft PR 编号与 URL。
4. 相对实施基线新增/修改的全部 migration 文件名。
5. migration 是否包含 Data Migration；数据迁移内容和不可逆风险。
6. `manage.py migrate` 前是否有额外检查/预处理。
7. 是否修改静态前端：`app.js`、`team.js`、`index.html`、`styles.css`、`profit-calculator.js` 等。
8. 实际 build 命令及是否必须执行。
9. 是否需要 `collectstatic`，实际命令是什么。
10. 是否新增/修改环境变量；只列变量名、用途、是否必填，禁止输出密钥值。
11. 是否新增/修改 Docker Compose、Caddy/Nginx、systemd service/timer。
12. 需要重启/重载的**真实服务名**。
13. 仓库中能否确认生产部署目录；若不能确认，明确写“无法从仓库确认”。
14. PostgreSQL 备份/恢复应沿用仓库当前部署规范；不要虚构数据库账号、库名或密码。
15. 健康检查 URL/命令。
16. 部署后必须执行的 smoke tests。
17. 回滚时应恢复代码到哪个部署前 SHA。
18. migration 是否可安全 reverse；若不安全，明确要求数据库备份恢复，而不是强行 reverse migrate。
19. 如果有数据模型从旧结构迁移到新结构（采购批次、调拨物流包、店铺授权等），必须说明回滚后新产生业务数据会怎样处理。

## Codex 应在实施分支新增/更新

`docs/deployment/aliyun/ERP-REPLENISHMENT-INTRANSIT-STORE-20260811.md`

该文档只记录已经确认的真实部署事实，不执行生产命令。

## 后续发给 ChatGPT 的最小信息

将 Codex 最终回复整体发回 ChatGPT，至少必须包含：

- Final HEAD SHA
- Draft PR
- Migrations
- Tests
- Deployment impact
- Rollback impact

ChatGPT 再生成一整段可复制到阿里云终端执行的命令，正常部署顺序必须包含：

1. 只读环境确认
2. 记录部署前代码 SHA
3. PostgreSQL 备份
4. 配置/服务文件备份（如本轮有改）
5. `git fetch`
6. checkout **精确最终 SHA**，禁止部署未知 HEAD
7. 安装/更新依赖（仅实际需要时）
8. Django migration
9. build / collectstatic（仅实际需要时）
10. 重启/重载真实服务
11. health check
12. 关键 smoke tests
13. 输出部署后 SHA
14. 独立回滚命令块

## 安全边界

- 禁止 `git pull` 后直接部署一个未固定 SHA 的版本。
- 有数据库结构/数据迁移时，执行 migration 前必须先备份数据库。
- 生产密钥不得进入 GitHub 文档、PR body 或 Codex 最终回复。
- Codex 不得自动执行生产部署或自动回滚。
- 数据库恢复属于破坏性操作，回滚命令必须要求人工确认。
- 如果最终 SHA、migration 或服务名发生变化，旧部署命令作废，必须重新生成。