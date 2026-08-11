# 东铂跨境 ERP：Codex 项目长期记忆

> 整理日期：2026-08-12（Asia/Shanghai）
> 适用仓库：`kevindongbo/codex`
> 本地工作区：`F:\codex-ozon`

## 1. 新对话记忆恢复说明

这是一个已经持续开发一段时间的跨境电商 ERP 项目。本文件由上一段 Codex 对话根据仓库实际文件、Git 状态、GitHub PR 状态、用户长期偏好和已展示的阿里云运维结果整理而成。

本文件用于恢复：

- 用户的长期沟通与协作习惯；
- 项目背景、架构和关键业务约束；
- 本地开发环境和常用检查命令；
- GitHub 分支、Commit、Pull Request 和推送流程；
- 已确认的阿里云生产运行方式；
- 仓库提供但尚未确认用于生产的 Docker/Caddy 方案；
- 部署、验证、数据库备份和回滚原则。

新的 Codex 开始任何任务前必须先完整阅读本文件。文件中已经确认的长期信息不要再次询问用户。长期习惯默认继续有效。

当前分支、Commit、Pull Request、镜像版本、数据库迁移状态和线上部署状态属于动态信息，必须结合当前仓库、GitHub 和服务器实际状态重新核验。如果本文件与当前代码、Git 状态或用户最新明确指令冲突，以当前实际状态和用户最新明确指令为准。

本文件使用以下状态标签：

- **已确认**：当前对话中有仓库文件、Git 输出、GitHub 返回或服务器输出支持，且未被后续信息推翻。
- **需要结合仓库核验**：信息在整理时成立，但可能随分支、提交、PR、迁移或线上部署变化。
- **待确认**：当前对话和仓库不足以证明，禁止当作事实使用。

## 2. 用户的沟通和工作习惯

### 2.1 长期有效的工作习惯

- 默认使用中文沟通。
- 表达直接、清楚、可执行；优先给结果，再说明必要原因和验证信息。
- 不反复解释已经明确的内容，不重复询问已经确认的问题。
- 能从代码、配置、Git 历史、需求文档或部署文件确认的信息，应自行检查。
- 只有真正会影响实现结果、数据安全或部署路径的关键缺失信息才询问用户。
- 提问时一次只问一个最关键的问题，用通俗中文说明为什么需要它。
- 修改前先阅读现有代码、数据模型、序列化器、服务、视图、路由、前端调用链和测试。
- 不盲目重写现有功能；优先沿用现有结构做增量修改。
- 只修改当前任务相关文件，不顺手改无关页面、模块或样式。
- 不破坏现有数据库、历史数据、库存流水和线上功能。
- 遇到 HTTP 500 要检查后端日志、请求负载和接口测试，不只凭截图猜原因。
- 实现任务必须真正修改代码并验证，不能只给分析、方案或建议。
- 完成后明确说明修改内容、修改文件、业务逻辑变化、测试结果和未完成项。
- 无论是否有数据库迁移，都要明确说明；没有迁移时写“本次无数据库迁移”。
- 涉及数据库变更时必须提供备份、迁移、验证和安全回滚路径。
- 只暂存和提交本次相关文件，保留用户已有的无关改动和未跟踪文件。
- GitHub 推送、PR 创建、生产部署和健康检查只能依据真实命令或连接器输出宣称成功。
- 用户通常希望 Codex 在测试通过后实际 Commit、Push，并创建或更新可审查 PR，而不是只给 Git 命令。
- 默认不直接修改 `main`，不自动合并 PR，不直接部署生产环境；当前任务明确授权时才例外。
- 当用户自行部署时，最后提供一整段可复制到阿里云黑框执行的 Bash 命令，不拆成零散步骤。
- 部署命令使用精确分支和完整 Commit SHA，不使用不确定的 `latest`。
- 部署命令必须包含部署前检查、代码和 PostgreSQL 备份、迁移、构建、静态文件、服务重启、Nginx 检查、健康检查、日志检查和回滚点。
- 不把“已提供部署命令”描述成“已部署成功”；必须看到服务器真实输出后才能确认。

### 2.2 不应固化为长期习惯的临时要求

以下内容通常属于单次任务，不能自动延续到下一任务：

- 某次需求指定的分支名、基础 SHA、PR 编号和 PR 标题；
- 某次任务要求“不部署”或“立即部署”的特殊范围；
- 某次验收要求的具体测试数量；
- 某次任务暂缓或允许的业务功能；
- 某次服务器故障排查中的临时命令或临时包安装。

每次任务以用户最新指令和对应需求文档为准。

## 3. 项目基本信息

### 3.1 已确认

- **项目名称**：东铂跨境 ERP。
- **项目用途**：支持跨境电商团队管理商品、SKU、采购、仓库库存、调拨、销售订单、退货、补货、店铺授权、竞品数据、汇率和利润试算。
- **GitHub 仓库**：`kevindongbo/codex`。
- **仓库地址**：`https://github.com/kevindongbo/codex`。
- **本地项目目录**：`F:\codex-ozon`。
- **前端目录**：仓库根目录，核心文件包括 `index.html`、`app.js`、`team.js`、`profit-calculator.js`、`styles.css`。
- **后端目录**：`backend/`，主要 ERP 应用位于 `backend/apps/erp/`。
- **数据库**：生产使用 PostgreSQL；未设置 `DATABASE_URL` 时，本地 Django 可使用 SQLite。
- **后端技术栈**：Python、Django 5.2、Django REST Framework、SimpleJWT、Gunicorn。
- **前端技术栈**：原生 HTML/CSS/JavaScript、ES Module、Node 构建脚本。
- **团队模式**：后端 PostgreSQL 是商品、采购、库存、订单、退货、权限和审计日志的事实来源。
- **公开站点域名**：仓库和既有部署资料使用 `https://dongbokeji.com`；当前可用性需要实时核验。
- **健康检查**：`GET /api/health/`，服务器本机通常检查 `http://127.0.0.1:8000/api/health/`。

### 3.2 主要业务模块

- 组织、成员、角色和仓库权限；
- 商品、图片、多 SKU 和供应商；
- 采购订单、收货、采购发货阶段和采购在途；
- 仓库库存、预占、可用库存、库存流水和手动调整；
- 仓库调拨、在途和部分收货；
- 销售订单、锁库、拣货、复核、出库和退货；
- 3/7/15/30 天销量加权补货建议；
- ERP 店铺、TikTok Shop OAuth 和授权连接；
- TikTok 马来西亚竞品/公开数据和 AlphaShop 配置；
- MYR/CNY 汇率；
- TikTok Shop 马来西亚利润试算和可保存计算策略；
- 审计日志和幂等业务动作。

### 3.3 已确认的关键业务规则

- 一个商品可有多个 SKU；库存、采购、成本和出库以 SKU 为粒度。
- 库存变化必须通过事务服务和不可变库存流水，不用普通 ORM 更新代替过账。
- 订单整单锁库：任一 SKU 不足时整单失败，不允许部分预占。
- 未映射的外部 SKU 必须返回明确 4xx 业务错误并包含 `external_sku_code`，不能出现 HTTP 500。
- 补货保留既有 3/7/15/30 天销量权重，不随意改动安全库存、波动、MOQ 和 pack 核心算法。
- 采购建议必须经人工确认后才能转成真实采购草稿，不能由 AI 自动下单。
- 生产数据库变更或恢复前必须备份。
- TikTok 公开数据、官方授权店铺数据和第三方选品数据是不同来源，不能互相冒充。
- 不伪造 TikTok 商品链接自动读取能力，不绕过登录、验证码或权限。

### 3.4 利润试算长期规则摘要

- 当前业务范围是 TikTok Shop 马来西亚，一级类目入口为“箱包”和“美妆个护”。
- 金额计算使用后端 Decimal 和后端统一核心公式。
- 跨境商家运费按包装后重量向上取整到 10g，只计算马来西亚价目表中的跨境段；本土商家运费为 RM0。
- 超过 30,000g 必须停止计算，不允许线性外推。
- 买家运费默认 RM0，不直接增加利润、不抵减商家运费，但进入交易手续费计费基数。
- 占比分母不包含买家运费。
- 每个 SKU 独立计算和四舍五入；平台支持费等按业务规则逐 SKU 或逐订单计算，必须以当前需求和后端代码核验。
- 费用归类、利润公式、九项金额汇总和计算策略已有多轮确认，新任务不得无需求依据地改写。

### 3.5 需要结合仓库核验的当前开发状态

- 当前本地分支：`codex/implement-erp-replenishment-intransit-store-20260811`。
- 整理时本地 HEAD：`5b86a1192a2cabbfa564de9e842aa39d93bd87fa`。
- 已完整测试的业务代码提交：`06c219dde3298955823d9ad77fee5a6f51d7fb3e`。
- 当前 Draft PR：`https://github.com/kevindongbo/codex/pull/12`。
- PR #12 Base：`codex/implement-profit-strategy-ui-fixes-20260805`。
- PR #12 Head：`codex/implement-erp-replenishment-intransit-store-20260811`。
- 整理时 PR 状态：Open、Draft、未合并。

### 3.6 PR #12 已完成的重要修改

- 修复未映射 SKU 在确认、锁库和确认并出库时可能触发 HTTP 500 的问题。
- 未映射 SKU 返回 HTTP 400、业务错误码和 `external_sku_code`。
- 增加订单人工选择仓库和出库前更换仓库的后端事务/API。
- 整单库存校验返回每个 SKU 的 `required`、`available`、`shortage`，库存不足时不建立部分预占。
- 修正采购待发货与采购在途计算口径，并统一采购和调拨在途余额来源。
- 新增采购发货确认、关闭未发货、关闭在途异常等服务/API。
- 增加补货建议分次转采购事件，实际创建采购 Draft 和采购行。
- 增加库存 pending/in-transit 来源明细 API 字段。
- 新增 `0030_purchase_stages_and_replenishment_conversion_events.py`。
- 新增前向修复迁移 `0031_repair_0028_replenishment_history.py`，不篡改已发布的 0028。

### 3.7 PR #12 尚未完成或仍需严格复验

- TikTok OAuth 与 ERP Store 的彻底分离、多远端店铺只选择一个绑定仍需复验和补齐。
- 采购和调拨完整多物流包 API/UI、包数量严格匹配、调拨草稿编辑同步预占仍未形成完整闭环。
- external SKU 映射后同店最近 30 天历史销量自动回填尚未完成。
- 库存页面尚未完整展示 pending/in-transit 来源明细。
- 前端逐 SKU 库存缺口专用展示仍不完整；后端已返回结构化缺口。
- 补货建议转采购的前端供应商选择流程仍需补齐。
- 退货回溯销售日逻辑在一个原订单存在多次发货时仍可能需要更明确的业务关联。

## 4. 项目规则和记忆文件

新的 Codex 默认按以下顺序开始任务：

1. 完整阅读 `CODEX_PROJECT_MEMORY.md`。
2. 阅读仓库根目录 `AGENTS.md`，以及相关子目录中适用的 `AGENTS.md`。
3. 按 `AGENTS.md` 读取 `agent-memory/INDEX.md`。
4. 从索引中只读取与当前任务相关的主题记忆，不批量读取全部 `agent-memory/` 或旧 `memory/`。
5. 检查当前 Git 分支、HEAD、工作区、远端和相关 PR 状态。
6. 核对交接文件和需求文件与当前代码的差异。
7. 阅读当前任务涉及的模型、服务、API、前端调用链和测试后再修改。

常用规则/说明文件：

- `AGENTS.md`：项目协作、安全和记忆读取规则。
- `agent-memory/INDEX.md`：主题记忆索引。
- `agent-memory/01_USER_AND_BUSINESS.md`：用户长期偏好。
- `agent-memory/02_TIKTOK_MALAYSIA.md`：TikTok 马来西亚数据与授权边界。
- `agent-memory/04_PRODUCTS_AND_HARD_CONSTRAINTS.md`：商品、SKU、图片和删除约束。
- `agent-memory/09_ERP_AND_TECH_PROJECTS.md`：ERP 架构、库存、利润和部署规则。
- `agent-memory/10_REUSABLE_TEMPLATES.md`：交付、迁移和排错模板。
- `README.md`：项目总体运行与 Docker/Caddy 自建部署。
- `backend/README.md`：Django API、业务动作和补货说明。
- `DEPLOYMENT_ERP_OPERATIONS.md`：已沿用的 systemd/Gunicorn/Nginx 运维方式。
- `docs/deployment/aliyun/`：每次需求对应的阿里云部署交接。

旧 `memory/` 目录是历史运维资料，只在新索引或当前任务明确指向时按需读取。

## 5. 本地开发环境

### 5.1 已确认

- **操作系统**：Windows。
- **常用终端**：PowerShell，由 Codex Desktop 调用。
- **工作区**：`F:\codex-ozon`。
- **Git**：Codex 捆绑 Git，整理时版本 `2.53.0.windows.3`。
- **Codex 捆绑 Node.js**：`C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`，整理时版本 `v24.14.0`。
- **Codex 捆绑 Python**：`C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`，整理时版本 `3.12.13`。
- **pnpm**：Codex fallback 路径可用，整理时版本 `11.16.0`。
- **GitHub CLI (`gh`)**：当前 PowerShell PATH 中未找到；GitHub 元数据/PR 可使用已连接的 GitHub App，是否安装系统 `gh` 待确认。
- **Docker / Docker Compose**：当前 PowerShell PATH 中未找到；仓库包含 Docker Compose 配置，但本机是否另有 Docker Desktop 待确认。
- **npm**：当前 PowerShell PATH 和捆绑 Node 目录均未确认可直接调用。
- **数据库**：本地默认可用 SQLite；团队/生产模式使用 PostgreSQL。
- **环境变量模板**：仓库根目录 `.env.example`。
- **生产环境变量文件**：已确认部署方式使用 `/opt/dongbo/app/.env`，不得读取、输出或提交其内容。

### 5.2 主要依赖

- Python：Django 5.2、Django REST Framework 3.17、SimpleJWT、CORS Headers、psycopg、Gunicorn、cryptography。
- 前端：原生 JS，无必需的前端框架依赖；`package.json` 构建脚本调用 `node scripts/build-site.mjs`。

### 5.3 常用后端检查命令

在可用 Python 环境中：

```powershell
Set-Location F:\codex-ozon\backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.erp.tests --noinput
```

如果系统 PATH 没有 Python，应先加载 Codex 工作区依赖，并使用其 Python 路径；不要自行假设全局 Python 已安装。仓库当前可能使用未跟踪的 `.codex-python-deps/` 提供 Django 包，接手时先核验。

### 5.4 常用前端检查命令

```powershell
Set-Location F:\codex-ozon
node --check app.js
node --check team.js
node --check profit-calculator.js
node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs
node scripts/build-site.mjs
```

如果 `node` 不在 PATH，使用 Codex 捆绑 Node.js 的绝对路径执行。

仓库脚本还支持：

```powershell
npm run build
npm test
```

但当前会话未确认 `npm` 可直接调用，因此优先使用实际可用的 Node 路径或重新加载工作区依赖。

### 5.5 其他检查

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git diff --check
git diff --stat
```

## 6. GitHub 仓库和分支规范

### 6.1 已确认

- **GitHub 用户/组织**：`kevindongbo`。
- **仓库**：`kevindongbo/codex`。
- **远端地址**：`https://github.com/kevindongbo/codex.git`。
- **默认分支**：`main`，但当前多个功能尚在未合并功能分支上。
- **分支命名习惯**：实现分支通常使用 `codex/implement-...`；文档分支通常使用 `docs/...`。
- 不从旧 `main` 重新开发尚未合并的功能；必须使用需求指定的真实基础分支和 SHA。
- 不直接提交到 `main`；只修改当前需求指定的功能分支。
- 一个现有 PR 的验收修复应继续推送原实施分支并更新原 PR，不另开重复业务 PR，除非用户明确要求。
- Commit 信息应简洁描述范围，例如 `fix(erp): ...`、`feat(profit): ...`、`docs(deploy): ...`。
- 只暂存当前任务相关文件，不使用 `git add .` 吞入无关未跟踪文件。
- 推送成功必须看到远端输出或连接器返回，不能只因本地 Commit 成功就声称已推送。

### 6.2 默认开发流程

```text
读取项目规则
→ 检查 git status
→ 确认当前分支和 HEAD
→ 获取远端最新状态
→ 核对需求文档和基础 SHA
→ 阅读相关代码和调用链
→ 小范围修改代码
→ 补充自动化测试
→ 执行 Django/Node 测试
→ 执行构建和静态检查
→ 检查 git diff / diff --check
→ 只暂存相关文件
→ Commit
→ Push 功能分支
→ 创建或更新可审查的 Draft PR
→ 提供阿里云更新、验证和回滚命令
```

### 6.3 PR 内容要求

PR 描述应至少包含：

- 每条需求完成状态；
- 修改内容和修改文件；
- API 和业务公式变化；
- 数据库 migration 及数据迁移风险；
- 每条测试命令和真实结果；
- 已知风险、未完成项和回滚方式；
- 最终精确 Commit SHA。

默认创建 Draft PR，不自动合并。生产部署由用户另行明确授权或自行执行。

### 6.4 推送成功核验

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
git ls-remote --heads origin <TARGET_BRANCH>
```

若本地网络环境无法运行 HTTPS remote helper，应通过已连接的 GitHub App 核验远端分支和 PR Head SHA，并如实说明本地限制。

## 7. 禁止提交到 GitHub 的内容

以下内容不得提交、粘贴进记忆、写进 PR 或打印到日志：

- 密码和验证码；
- Token、GitHub Token、OAuth access/refresh token；
- 阿里云 AccessKey；
- SSH 私钥和服务器密码；
- 数据库密码和完整连接串；
- 生产环境 `.env`；
- DeepSeek、AlphaShop、TikTok 或其他第三方 API Key/Secret；
- 真实用户数据和未经脱敏的订单数据；
- 数据库备份或生产媒体备份；
- 临时调试文件、缓存目录和大型日志；
- 原始业务 Excel，除非用户明确要求且已确认不含敏感内容；
- 无关截图、部署压缩包、补丁归档和本地运行时目录；
- 包含敏感信息的配置、Shell 历史或服务器输出。

当前工作区存在较多未跟踪的本地依赖、临时目录、部署包、截图和历史资料。不得使用宽泛暂存命令把它们带入提交。发现疑似敏感信息时，应停止暂存/推送，说明文件路径和风险，但不要回显敏感值。

所有示例秘密统一使用占位符：

```text
<ALIYUN_SERVER_IP>
<ALIYUN_SSH_USER>
<ALIYUN_ACR_REGISTRY>
<ALIYUN_ACR_USERNAME>
<ALIYUN_ACR_PASSWORD>
<GITHUB_TOKEN>
<DATABASE_PASSWORD>
<PRODUCTION_ENV_FILE>
```

## 8. 阿里云服务器和镜像部署

### 8.1 当前生产运行方式：已确认

- **用途**：运行东铂跨境 ERP 生产站点。
- **地区**：阿里云 ECS Workbench 地址曾显示 `cn-guangzhou`，即广州区域；实例与网络状态仍需现场核验。
- **应用代码目录**：`/opt/dongbo/app`。
- **Python 虚拟环境**：`/opt/dongbo/venv`。
- **Django/Gunicorn systemd 服务**：`dongbo-erp`。
- **Gunicorn 监听**：`127.0.0.1:8000`。
- **数据库类型**：PostgreSQL。
- **数据库名**：`dongbo_erp`。
- **反向代理**：Nginx。
- **生产环境文件**：`/opt/dongbo/app/.env`。
- **备份根目录**：`/opt/dongbo/backups/`。
- **本机健康检查**：`http://127.0.0.1:8000/api/health/`。
- **公网检查**：`https://dongbokeji.com/`。
- **应用日志**：`journalctl -u dongbo-erp`。
- **Nginx 错误日志**：`/var/log/nginx/error.log`。
- **数据库迁移**：在 `/opt/dongbo/app/backend` 使用 `/opt/dongbo/venv/bin/python manage.py migrate --noinput`。
- **静态资源**：`manage.py collectstatic --noinput`。
- **服务更新**：当前确认流程是 Git 精确 SHA + Python 依赖 + 前端构建 + Django migration + collectstatic + systemd restart + Nginx reload。

### 8.2 当前生产状态：需要结合服务器核验

- 2026-08-11 的服务器截图曾证明旧实施提交 `d47fed21f2f45d747f87d6c4efc45b3e93020aa3` 部署成功，迁移 `0028`、`0029` 已应用，服务和健康检查正常。
- 后续已提供部署 PR #12 当前 Head `5b86a1192a2cabbfa564de9e842aa39d93bd87fa` 的命令，但本对话没有收到该命令最终执行成功的服务器输出。
- 因此新对话不能假设生产已经运行 `5b86a119...`，必须先执行：

```bash
git -C /opt/dongbo/app rev-parse HEAD
systemctl is-active dongbo-erp
curl -fsS http://127.0.0.1:8000/api/health/
/opt/dongbo/venv/bin/python /opt/dongbo/app/backend/manage.py showmigrations erp
```

### 8.3 仓库自带 Docker/Caddy 方案：已确认存在，但不是已确认生产方式

仓库根目录包含 `docker-compose.yml`、`backend/Dockerfile`、`deploy/Caddyfile`、`deploy/backup.sh` 和 `deploy/restore.sh`。

Compose 服务：

- `db`：`postgres:16-alpine`；
- `api`：本地构建 `backend/Dockerfile`；
- `caddy`：`caddy:2.10-alpine`，同时提供静态前端和反向代理；
- Compose 项目默认名：`dongbo-erp`。

该方案没有单独的前端容器镜像，静态前端由 Caddy 挂载和提供。当前代码也没有部署 Redis 或 MinIO。不能凭空写出前端镜像、Redis 服务或对象存储容器。

### 8.4 ACR 信息：待确认

当前仓库和对话没有确认正在使用阿里云容器镜像服务 ACR，也没有确认以下信息：

- ACR Registry 地址；
- ACR 地区；
- 命名空间；
- 镜像仓库名称；
- 前端镜像名称；
- 后端镜像名称；
- 镜像标签规则；
- 生产 Compose 是否从 ACR 拉取镜像。

因此，在用户提供或服务器配置证明这些信息前，只能使用占位符，不得生成看似真实的 ACR 地址、镜像名或容器名。当前生产默认按 systemd/Gunicorn/Nginx 流程处理，不要混用 Docker/ACR 命令。

### 8.5 其他待确认

- 服务器公网 IP、SSH 用户和密码；
- Nginx 站点配置文件的具体路径；
- PostgreSQL 角色名和认证方式；
- ACR 登录凭据；
- 当前生产是否启用了 `dongbo-replenishment-ai.timer` 和 `dongbo-exchange-rates.timer`；
- 当前生产最终部署 SHA、迁移状态和公网页面验收结果。

## 9. 阿里云终端更新命令

### 9.1 当前已确认生产方式的标准模板

Codex 完成并推送代码后，应把 `<TARGET_BRANCH>` 和 `<EXACT_COMMIT_SHA>` 替换为真实值，再给用户一整段 Bash。不要使用 `latest`。

```bash
set -Eeuo pipefail

APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
APP_SERVICE=dongbo-erp
DB_NAME=dongbo_erp
TARGET_BRANCH=<TARGET_BRANCH>
EXACT_SHA=<EXACT_COMMIT_SHA>
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/opt/dongbo/backups/$STAMP
DB_TMP=/tmp/${DB_NAME}-${STAMP}.dump

test -d "$APP/.git"
test -x "$VENV/bin/python"
test -f "$APP/backend/manage.py"
test -f "$APP/.env"
git -C "$APP" status --short
git -C "$APP" rev-parse HEAD
sudo systemctl status "$APP_SERVICE" --no-pager -l

sudo mkdir -p "$BACKUP_DIR"
git -C "$APP" rev-parse HEAD | sudo tee "$BACKUP_DIR/code-commit.txt" >/dev/null
sudo tar -C /opt/dongbo --exclude='app/.git' --exclude='app/.env' --exclude='app/backend/staticfiles' -czf "$BACKUP_DIR/app.tar.gz" app
sudo -u postgres pg_dump -Fc -f "$DB_TMP" "$DB_NAME"
sudo mv "$DB_TMP" "$BACKUP_DIR/${DB_NAME}.dump"
sudo chmod 600 "$BACKUP_DIR/${DB_NAME}.dump"

if test -n "$(git -C "$APP" status --porcelain)"; then
  git -C "$APP" stash push --include-untracked -m "pre-deploy-$STAMP"
fi
test -z "$(git -C "$APP" status --porcelain)"

git -C "$APP" fetch origin "$TARGET_BRANCH"
git -C "$APP" cat-file -e "$EXACT_SHA^{commit}"
git -C "$APP" merge-base --is-ancestor "$EXACT_SHA" "origin/$TARGET_BRANCH"
git -C "$APP" checkout --detach "$EXACT_SHA"
test "$(git -C "$APP" rev-parse HEAD)" = "$EXACT_SHA"

"$VENV/bin/pip" install -r "$APP/backend/requirements.txt"
cd "$APP"
node scripts/build-site.mjs

set -a
. "$APP/.env"
set +a
cd "$APP/backend"
"$VENV/bin/python" manage.py check
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput

sudo systemctl restart "$APP_SERVICE"
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl is-active --quiet "$APP_SERVICE"

HEALTH_OK=0
for ATTEMPT in $(seq 1 15); do
  if curl -fsS --max-time 15 http://127.0.0.1:8000/api/health/; then
    HEALTH_OK=1
    break
  fi
  sleep 2
done
test "$HEALTH_OK" -eq 1

curl -fsS --max-time 20 -o /dev/null -w 'PUBLIC_HTTP_STATUS=%{http_code}\n' https://dongbokeji.com/
sudo journalctl -u "$APP_SERVICE" --since '10 minutes ago' -n 120 --no-pager
sudo tail -n 80 /var/log/nginx/error.log
printf '\nDEPLOY_SUCCESS SHA=%s BACKUP_DIR=%s\n' "$EXACT_SHA" "$BACKUP_DIR"
```

只有看到脚本最后的 `DEPLOY_SUCCESS`、健康接口成功响应和服务状态正常，才可报告部署成功。

### 9.2 当前生产方式的安全回滚模板

数据库恢复会覆盖迁移后的数据，只能在确认备份目录和影响范围后执行。`<BACKUP_DIR>` 和 `<PREVIOUS_SHA>` 必须替换为部署输出中的真实值。

```bash
set -Eeuo pipefail

APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
APP_SERVICE=dongbo-erp
DB_NAME=dongbo_erp
BACKUP_DIR=<BACKUP_DIR>
PREVIOUS_SHA=<PREVIOUS_SHA>

case "$BACKUP_DIR" in
  /opt/dongbo/backups/*) ;;
  *) echo '备份目录不合法' >&2; exit 1 ;;
esac

test -f "$BACKUP_DIR/${DB_NAME}.dump"
test -f "$BACKUP_DIR/code-commit.txt"
test "$(cat "$BACKUP_DIR/code-commit.txt")" = "$PREVIOUS_SHA"
git -C "$APP" cat-file -e "$PREVIOUS_SHA^{commit}"

sudo systemctl stop "$APP_SERVICE"
sudo -u postgres pg_restore --clean --if-exists --no-owner -d "$DB_NAME" "$BACKUP_DIR/${DB_NAME}.dump"
git -C "$APP" checkout --detach "$PREVIOUS_SHA"

set -a
. "$APP/.env"
set +a
cd "$APP"
node scripts/build-site.mjs
cd "$APP/backend"
"$VENV/bin/python" manage.py collectstatic --noinput

sudo systemctl start "$APP_SERVICE"
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl is-active --quiet "$APP_SERVICE"
curl -fsS --max-time 15 http://127.0.0.1:8000/api/health/
sudo journalctl -u "$APP_SERVICE" -n 120 --no-pager
printf '\nROLLBACK_SUCCESS SHA=%s BACKUP_DIR=%s\n' "$PREVIOUS_SHA" "$BACKUP_DIR"
```

### 9.3 Docker/Caddy 自建部署模板

只有当前服务器实际采用仓库根目录 `docker-compose.yml` 时才使用：

```bash
set -Eeuo pipefail
cd <SERVER_PROJECT_PATH>
git status --short
sh deploy/backup.sh
git fetch origin <TARGET_BRANCH>
git checkout --detach <EXACT_COMMIT_SHA>
test "$(git rev-parse HEAD)" = '<EXACT_COMMIT_SHA>'
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api caddy
curl -fsS http://localhost/api/health/
```

该仓库 Compose 当前是本地构建 `api`，不是已确认的 ACR 拉取流程。

### 9.4 ACR 模板

只有实际确认 ACR 地址、命名空间、镜像名、标签和 Compose 文件后才生成可执行命令。安全占位形式如下，不能原样执行：

```bash
docker login <ALIYUN_ACR_REGISTRY> -u <ALIYUN_ACR_USERNAME>
export IMAGE_TAG=<EXACT_COMMIT_SHA>
docker compose -f <PRODUCTION_COMPOSE_FILE> pull
docker compose -f <PRODUCTION_COMPOSE_FILE> up -d
docker compose -f <PRODUCTION_COMPOSE_FILE> ps
```

密码应通过终端安全输入或凭据助手提供，不写进脚本、文档或 Git。

## 10. 当前项目状态

### 10.1 需要结合仓库核验的动态状态

- 当前主要开发模块：补货、采购/调拨在途、销售订单仓库选择、ERP Store/TikTok OAuth 分离和库存来源明细。
- 当前实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`。
- 当前本地/PR Head：`5b86a1192a2cabbfa564de9e842aa39d93bd87fa`。
- 已测试业务代码 SHA：`06c219dde3298955823d9ad77fee5a6f51d7fb3e`；其后的 Head 只增加部署交接文档。
- Draft PR：#12，整理时 Open、Draft、未合并。
- 生产是否已更新到该 Head：未确认。
- 生产迁移 `0030`、`0031` 是否已应用：未确认。

### 10.2 最近一次已执行的自动化验证

```text
python backend/manage.py check                                      PASS
python backend/manage.py makemigrations --check --dry-run          PASS
python backend/manage.py test apps.erp.tests --noinput              PASS（133 tests）
node --check app.js                                                 PASS
node --check team.js                                                PASS
node --check profit-calculator.js                                  PASS
node --test tests/site.test.mjs                                    PASS（15 tests）
node --test tests/domain.test.mjs                                  PASS（16 tests）
node --test tests/team.test.mjs                                    PASS（20 tests）
node scripts/build-site.mjs                                        PASS
```

新对话不能把这些旧测试结果当成修改后的结果。任何新修改完成后必须重新运行适用测试。

### 10.3 新 Codex 接手后的第一步

1. 检查 `git status --short`，不要触碰无关未跟踪文件。
2. 检查当前分支、HEAD 和最近提交。
3. 通过 GitHub 核验 PR #12 的 Head、评论、Review 和是否仍为 Draft。
4. 阅读：
   - `requirements/2026-08-11_1135_UTC+8/ERP_PR12_REMEDIATION_REQUIREMENTS.md`；
   - `requirements/2026-08-11_1135_UTC+8/CODEX_FIX_PROMPT.md`；
   - 原始需求 `requirements/2026-08-11_0157_UTC+8/ERP_REPLENISHMENT_INTRANSIT_STORE_REQUIREMENTS.md`。
5. 如果需求文件只存在远端文档分支，用 `git show origin/<docs-branch>:<path>` 读取，不切换到旧 `main`。
6. 对照 PR 中未完成项检查现有实现、测试覆盖和最新 Review。
7. 用户要求部署前，先核验服务器当前 SHA、迁移、服务状态和健康接口。

### 10.4 最容易被误改的功能

- 补货 3/7/15/30 天权重和安全库存、波动、MOQ、pack 核心算法；
- `on_hand`、`reserved`、`available`、采购待发货和采购/调拨在途之间的库存事实来源；
- 采购和调拨的幂等、部分收货、异常关闭和库存流水；
- 订单整单锁库、仓库权限和未映射外部 SKU；
- TikTok OAuth 与 ERP Store 的组织隔离和单店绑定；
- 利润试算后端统一公式、运费价表、九项金额汇总和策略事务；
- 商品编辑弹窗现有图片区域和多商品采购订单既有结构；
- systemd 生产流程与仓库 Docker/Caddy 备用方案，二者不可混用。

## 11. 完成任务后的固定汇报格式

新的 Codex 每次完成代码任务后，尽量按以下结构汇报；没有内容也要明确写“无”“未执行”或“待确认”。

```markdown
## 完成结果

## 修改内容

## 修改文件

## 业务逻辑变化

## 数据库迁移

本次无数据库迁移。

## 测试结果

## 构建和静态检查

## GitHub Commit

## GitHub 分支

## Pull Request

## 阿里云更新命令

## 回滚方式

## 注意事项
```

如果有数据库迁移，将“本次无数据库迁移”替换为迁移文件、数据影响、备份、验证和回滚说明。

最后必须区分以下状态：

- 代码已修改；
- 测试已通过；
- Commit 已创建；
- 分支已推送；
- PR 已创建或更新；
- 部署命令已提供；
- 生产已实际部署；
- 部署后健康检查已通过。

这些状态不能互相替代，也不能在没有真实证据时合并成“全部完成”。
