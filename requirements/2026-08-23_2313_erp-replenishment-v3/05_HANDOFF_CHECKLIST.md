# Codex → GitHub → 阿里云部署交接清单

- 需求版本：V3 Detailed Revision 1
- 详细版覆盖更新时间：2026-08-23 23:26 +08:00
- 实现分支：`codex/erp-replenishment-v3-implementation-20260823`

Codex 完成开发后必须明确回传并确认：

- [ ] 代码已经实际 push 到 GitHub 实现分支，不只是本地修改
- [ ] 最终实现分支名
- [ ] 最终 commit SHA
- [ ] 与开发基线相比的修改文件列表
- [ ] 新增文件列表
- [ ] migration 文件名及每个 migration 的作用
- [ ] migration 是否包含数据迁移及风险
- [ ] 后端测试命令和结果
- [ ] 前端测试命令和结果
- [ ] 失败测试及原因
- [ ] 跳过/无法执行测试及原因
- [ ] 是否需要 `python manage.py migrate`
- [ ] 是否需要 `collectstatic`
- [ ] 是否需要前端 build
- [ ] 是否新增/修改 Python 依赖
- [ ] 是否新增/修改前端依赖
- [ ] 是否新增环境变量
- [ ] 是否新增 cron / Celery / management command / systemd timer
- [ ] 每日自动补货检查的实际运行方式
- [ ] 需要重启哪些服务
- [ ] 已知风险
- [ ] 未完成项
- [ ] 推荐回滚方式

## 部署交接原则

Codex push 完成后，不要直接猜阿里云部署命令。先由 ChatGPT 重新读取 GitHub 最终实现分支、最终 SHA、diff、migration、依赖和部署相关文件，再生成可以直接复制到阿里云 SSH 黑框执行的命令。

部署命令必须至少包含：服务器状态检查、保存部署前 SHA、fetch、checkout 固定最终 SHA、必要依赖安装、migration、必要 build/collectstatic、定时任务处理、服务重启、健康检查、日志检查和回滚命令。
