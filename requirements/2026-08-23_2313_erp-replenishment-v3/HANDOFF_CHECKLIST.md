# Codex 修改完成后的交接清单

需求上传时间：2026-08-23 23:13 +08:00

Codex 完成代码后，必须先 push 到：

`codex/erp-replenishment-v3-implementation-20260823`

然后把以下信息完整返回，后续才能生成阿里云服务器“黑框”部署命令：

- GitHub 仓库：`kevindongbo/codex`
- 实现分支名
- 最终 commit SHA
- migration 文件名
- 测试命令与结果
- 是否要求执行 `python manage.py migrate`
- 是否要求 `collectstatic`
- 是否有前端 build 步骤
- 是否新增定时任务/cron/Celery/management command
- 生产服务实际进程名称（如果仓库中可确认）
- 需要重启的服务
- 新增环境变量（如无写无）
- 代码变更中是否包含依赖文件变化
- 未完成项/已知风险

## 部署前安全要求

生成阿里云命令时，应先做：

1. `git status` 检查服务器是否有未提交本地修改；
2. 记录当前生产 commit SHA，作为回滚点；
3. `git fetch` 后 checkout 指定实现分支/commit；
4. 根据实际变更决定是否安装依赖、migrate、collectstatic、build；
5. 重启实际服务；
6. 做 Django check / 健康检查；
7. 若失败，按记录的旧 SHA 回滚。

不要在不知道生产目录、Python 虚拟环境、服务名称、当前部署分支的情况下编造绝对路径或服务名。

用户把 Codex 的最终报告发回 ChatGPT 后，再根据最终 commit 和项目真实部署结构生成可复制执行的阿里云终端命令。