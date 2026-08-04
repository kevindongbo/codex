# 阿里云部署交接规则

- 文档上传时间：2026-08-05 01:08（UTC+8）
- 当前阶段：仅需求固化，尚未形成最终可部署代码 SHA。

## 为什么现在不能给最终黑框命令

阿里云部署命令必须绑定 Codex 实际完成、测试并推送后的精确提交 SHA。迁移文件、依赖、静态资源版本和回滚点都可能随最终实现变化。提前填写固定 SHA 会导致部署错误或回滚失效。

## Codex 完成后必须提供

1. 实施分支：`codex/implement-profit-settlement-strategies-20260805`
2. Draft PR 地址和编号。
3. 最终精确提交 SHA。
4. 新增 migration 文件名。
5. 实际执行过的测试命令和结果。
6. 是否增加 Python/Node 依赖。
7. 阿里云部署文档：`docs/deployment/aliyun/ERP-PROFIT-REQ-20260805-01.md`。

## 最终部署命令必须遵循现有服务器配置

- 应用目录：`/opt/dongbo/app`
- Python 虚拟环境：`/opt/dongbo/venv`
- systemd 服务：`dongbo-erp`
- PostgreSQL 数据库：`dongbo_erp`
- 健康检查：`http://127.0.0.1:8000/api/health/`

## 最终黑框命令应包含

1. 设置变量并确认目标 SHA；
2. 备份当前代码；
3. 使用 `pg_dump` 备份 PostgreSQL；
4. 拉取 GitHub 并检出精确 SHA；
5. 安装后端依赖；
6. 执行 Django migrations；
7. 构建前端静态资源；
8. 执行 `collectstatic`；
9. 重启并检查 `dongbo-erp`；
10. 检查并重载 nginx；
11. API 健康检查；
12. 页面人工验收；
13. 出错时恢复数据库和旧代码的完整回滚命令。

代码 PR 尚未完成前，本文件只作为交接清单，不包含虚假的最终 SHA 或声称已验证的命令。
