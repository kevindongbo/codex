# 东铂跨境 ERP — Codex 项目长期记忆

> 最后整理日期：2026-08-21（Asia/Shanghai）
> 本文件不包含密码、Token、私钥、AccessKey、数据库密码、服务器登录凭据或生产 `.env` 内容。

## 1. 新对话记忆恢复说明

这是一个已经持续开发较长时间的项目。本文件由上一段 Codex 对话整理而成，是东铂跨境 ERP 的长期项目记忆、协作规则和上下文来源，包含用户长期习惯、项目结构、GitHub 流程、阿里云生产架构以及部署和回滚规则。

新的 Codex 开始任何任务前必须完整阅读本文件。文件中已经确认且仍然有效的信息不要再次询问用户；长期沟通和工作习惯默认继续有效。

分支、Commit、Pull Request、迁移应用情况、服务器运行状态和线上版本属于动态信息，必须结合当前仓库、GitHub 和服务器真实输出重新核验。若本文件与当前代码、Git 状态、服务器真实输出或用户最新明确指令冲突，以当前实际状态和用户最新明确指令为准。不要从旧 `main` 重新开发尚未合并但已存在于功能分支上的功能。

信息标记含义：

- **已确认**：当前对话已经明确确认，且未被后续信息推翻。
- **需要结合仓库核验**：会随分支、Commit、PR、迁移或线上部署变化。
- **待确认**：现有资料无法可靠确认，不得猜测。

仓库中的旧 `PROJECT_MEMORY.md` 是较早阶段的历史材料，不是当前 ERP 的权威交接文件；只有在当前任务明确需要追溯历史时才参考。

## 2. 用户的沟通和工作习惯

### 2.1 长期有效的工作习惯

- 默认使用中文沟通，表达直接、清楚、可执行。
- 不反复解释已经明确的内容，不重复询问已经确认的问题。
- 能从代码、配置、Git 历史、需求文件、项目文档或服务器输出确认的信息，应自行检查。
- 只有缺失信息会直接影响实现结果、业务口径或数据安全时才提问；一次只问最关键的一个问题。
- 简单且有行业常规做法的细节可根据正常 ERP 逻辑自行决定；可能存在业务争议的口径应先确认。
- 修改前先阅读现有模型、服务、序列化器、视图、路由、前端调用链和测试，不盲目重写。
- 优先复用现有结构并增量修改，不创建第二套重复模型或平行流程绕过真实问题。
- 只修改当前任务相关内容，不顺手重写无关页面和模块。
- 不破坏数据库历史数据、库存流水、锁库与释放逻辑、利润公式、补货算法和线上功能。
- 完成代码任务后应给出实际结果，不只提供方案；需要明确修改内容、文件、业务变化、测试结果和迁移情况。
- 有数据库变更时必须提供 migration、备份、验证和回滚方式；无迁移也要明确说明。
- 用户通常要求 Codex 实际 Commit、Push 到正确功能分支并创建或更新 Draft Pull Request，而不是只告诉用户如何提交。
- 未经明确授权，不自动合并，不直接部署生产。
- 最终提供的阿里云命令必须依据仓库和服务器真实配置，使用最终精确 Commit SHA，并整理为一整段可复制到服务器黑色终端执行的 Bash。
- 提供部署命令不等于部署成功；只有收到真实服务器输出后，才能确认部署和健康检查成功。

### 2.2 不应固化为长期规则的临时要求

具体需求编号、某一次指定的分支名、Commit 信息、PR 目标分支、镜像标签和迁移编号都属于任务或时间点信息。新任务应优先服从用户当次指令和仓库真实状态。

## 3. 项目基本信息

### 3.1 已确认

- **项目名称**：东铂跨境 ERP / 东铂跨境运营系统。
- **项目用途**：面向东铂跨境团队的内部 ERP，覆盖商品与 SKU、店铺、采购与在途、多仓库存、仓间调拨、订单履约、智能补货、数据分析、利润试算和达人管理。
- **GitHub 仓库**：`kevindongbo/codex`。
- **仓库地址**：`https://github.com/kevindongbo/codex`。
- **本地仓库目录**：`F:\codex-ozon`。
- **前端位置**：仓库根目录的静态 HTML/CSS/JavaScript，核心文件包括 `index.html`、`styles.css`、`app.js`、`team.js`、`profit-calculator.js`、`runtime-config.js`。
- **后端位置**：`backend/`；主要 Django 应用为 `backend/apps/erp/`。
- **生产数据库**：PostgreSQL。
- **主要技术栈**：Django、Django REST Framework、PostgreSQL、Gunicorn、systemd、Nginx、原生 JavaScript、Node.js 内置测试运行器、Playwright。
- **仓库还保留的容器化能力**：根目录 `docker-compose.yml`、`backend/Dockerfile` 和 `deploy/Caddyfile`，服务为 `db`、`api`、`caddy`。这是本地或备用容器化方案，不代表当前生产架构。

### 3.2 主要业务模块

- 商品中心、SKU、图片与商品链接。
- 自有店铺与店铺商品。
- 采购单、采购在途、部分收货和异常关闭。
- 仓库、库存余额、库存流水、手工调整与撤回。
- 仓间调拨、多包裹、空物流单号补录、部分收货、异常关闭。
- 销售订单、仓库选择、整单锁库、换仓、出库、ERP 内部取消与恢复履约。
- 智能补货、仓库维度近 7 天出库明细和补货建议。
- 数据分析：概览、店铺、SKU 和竞品分析。
- 利润试算：组织共享当前配置、正式策略、广告返点、真实 ROI/CPA、可保存利润方案和版本。
- 达人管家：达人、内容、合作、履约、样品、归因和无归因处理。
- 智能选品与第三方平台连接。

### 3.3 已完成的重要功能（当前对话确认）

- 利润 working config 组织共享、debounce 自动保存、F5 恢复、临时 SKU 试算输入隔离、乐观锁冲突处理。
- 正式利润策略继续独立保存；激活策略与 working config revision 协同。
- 广告返点百分比、返点前后广告成本、真实 ROI 和真实 CPA 计算。
- 利润试算方案持久化、版本、历史查看、重算、保存新版本和另存为。
- 正式仓库选择弹窗，按 SKU 显示 required / available / shortage，库存不足仓不可选；不再要求用户输入 UUID。
- ERP 内部取消订单、原子释放 reservation、已出库禁止取消、平台重同步不自动恢复、人工恢复履约。
- 调拨多包裹、物流单号可空、包内 SKU 数量校验、部分收货、异常关闭以及 `received_quantity` / `exception_closed_quantity` 区分。
- 结束调拨时，未收余量作为异常关闭，目的仓在途归零，不增加目的仓现货，也不恢复来源仓库存。
- 库存列表在途来源同时汇总采购在途和仓间调拨在途。
- 智能补货表头粘性定位；查看周期明细调整为各仓近 7 天真实出库数量。
- 店铺保存后立即显示且刷新后仍显示；修复前端状态规范化丢失 `stores`、`storeProducts`、`profitCategories` 的问题。
- 数据分析入口和达人管家页面、API 与权限链路。

### 3.4 业务口径中已经最终确认的规则

- “在途库存”需要计算所有有效来源的总和，包括采购在途和仓间调拨在途，不只计算单一来源。
- 调拨已结束后，任何未实际收到的数量不能继续留在在途；应以异常关闭处理。
- 异常关闭数量不计入 `received_quantity`，不增加目的仓 `on_hand`，也不恢复来源仓库存。
- 日均出库按原订单销售发生日统计；销售出库计入总量，退货按原销售日冲减。
- 手工调整、仓间调拨和已撤回流水不计入销售日均出库。
- 创建订单库存不足时，保存为“库存不足”订单，不进行部分扣减。
- 取消按钮一次点击只发起一次 API 请求。
- ERP 取消只停止 ERP 内部履约，不调用 TikTok、Shopee、Ozon 等平台 API 取消买家平台订单。
- 利润方案允许信息未填写完整时保存为草稿，后续可补全、重算并形成新版本。

## 4. 项目规则和记忆文件

开始任何任务的默认顺序：

1. 完整阅读本文件 `CODEX_PROJECT_MEMORY.md`。
2. 阅读仓库根目录及当前任务适用子目录中的 `AGENTS.md`。
3. 阅读 `agent-memory/INDEX.md`。
4. 只打开当前任务相关的主题记忆；不要批量加载整个 `agent-memory/` 或旧 `memory/`。
5. 检查当前 Git 分支、HEAD、工作区、远端和相关 Pull Request 状态。
6. 核对交接文件、需求文档与仓库当前实际状态。
7. 阅读任务涉及的模型、服务、序列化器、视图、路由、前端调用链和测试。
8. 明确修改范围后再实施。

仓库规则文件：

- `AGENTS.md`：项目协作、安全和记忆读取规则。
- `agent-memory/INDEX.md`：主题记忆索引。
- `agent-memory/00_MEMORY_PROTOCOL.md`：记忆维护协议。
- `agent-memory/09_ERP_AND_TECH_PROJECTS.md`：ERP 与技术项目主题记忆。
- `docs/NEXT_CHAT_HANDOFF_DONGBO_ERP.md`：上一阶段的 ERP 技术交接，使用前核验动态信息。
- `docs/deployment/aliyun/ERP-REQ-20260804.md`：阿里云部署背景与历史配置说明。
- `requirements/`：每个任务的需求与验收标准；用户指定某个 `01_REQUIREMENTS.md` 时，以其为当次最终业务验收标准。

## 5. 本地开发环境

### 5.1 已确认

- **操作系统**：Windows。
- **常用终端**：PowerShell；服务器端为 Bash。
- **本地 Git 仓库**：`F:\codex-ozon`。
- **Git**：可用。
- **前端**：原生 JavaScript/HTML/CSS，Node ESM 项目。
- **后端**：Python、Django、Django REST Framework。
- **后端依赖文件**：`backend/requirements.txt`。
- **前端依赖文件**：`package.json`；存在 `pnpm-lock.yaml`。
- **本地/备用容器配置**：根目录 `docker-compose.yml`，包含 PostgreSQL 16、Django API 和 Caddy。
- **环境变量模板**：根目录 `.env.example`；真实 `.env` 不能提交或输出。

### 5.2 依赖版本范围

- Django `>=5.0,<6.0`
- Django REST Framework `>=3.15,<4.0`
- PostgreSQL 驱动 `psycopg[binary]>=3.1,<4.0`
- Gunicorn `>=22,<24`
- Playwright 开发依赖 `^1.62.1`

具体已安装的 Node.js、Python、npm、pnpm 和依赖版本会随环境变化，执行前应核验。Codex 桌面环境若找不到系统 Node/Python，可先加载工作区捆绑依赖运行时。

### 5.3 常用检查、测试与构建命令

后端：

```bash
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test apps.erp.tests --noinput
```

前端语法检查：

```bash
node --check app.js
node --check team.js
node --check profit-calculator.js
```

前端测试：

```bash
node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs
```

构建与完整前端命令：

```bash
node scripts/build-site.mjs
npm test
npm run test:browser
```

若仓库命令已经调整，以最新 `package.json`、测试目录和 CI 配置为准，但所有适用的现有后端、前端、构建、静态检查和真实浏览器回归都应运行。测试必须报告真实输出，不得虚构。

### 5.4 待确认

- 系统全局 Node.js、npm、pnpm 和 Python 的具体版本。
- GitHub CLI `gh` 是否在每个本地环境中安装；当前 GitHub 状态可通过连接器或 Git 命令核验。
- 本机 Docker 与 Docker Compose 是否已安装并运行。
- 本地开发所使用的具体 `.env` 文件和本地 PostgreSQL实例；不得猜测或输出其内容。

## 6. GitHub 仓库和分支规范

### 6.1 已确认

- **GitHub 用户/组织**：`kevindongbo`。
- **仓库**：`codex`。
- **地址**：`https://github.com/kevindongbo/codex`。
- **默认分支**：`main`。
- **远端**：`origin` 和 `github` 均指向该 GitHub 仓库；另有与项目站点相关的远端时，不应误推送。
- **功能分支命名偏好**：`codex/<task-name>-<date-or-id>`。
- 不直接修改或推送 `main`，不自动 merge。
- 只在正确功能分支上修改，完成后实际 Commit、Push 并创建或更新可审查的 Draft Pull Request。
- PR 应写明修改内容、测试结果、迁移说明、风险和回滚说明。
- 只暂存当次相关文件。工作区可能长期存在用户自己的未跟踪文件，禁止用 `git add -A`、`git clean`、`git reset --hard` 或强推破坏它们。

### 6.2 默认开发流程

1. 读取项目规则。
2. 执行 `git status --short`、`git branch -vv`、`git log --oneline --decorate -20` 和 `git reflog -20`。
3. 检查当前分支和已有未推送代码。
4. `git fetch` 并核验远端。
5. 只在目标功能分支执行 `git pull --ff-only`。
6. 阅读相关代码和测试。
7. 增量修改。
8. 执行后端测试、前端测试、构建和静态检查。
9. 执行 `git diff` 与 `git diff --check`。
10. 只暂存相关文件并 Commit。
11. Push 功能分支。
12. 创建或更新 Draft PR。
13. 提供基于最终精确 SHA 的阿里云更新和回滚命令。

确认推送成功至少应核验：

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/<TARGET_BRANCH>
git log -1 --oneline --decorate
```

本地 HEAD 与远端目标分支 SHA 必须一致；还应核验 PR 的 head SHA、base、Draft/merge 状态和 CI。

### 6.3 需要结合仓库核验的当前快照

截至 2026-08-21：

- 当前功能分支：`codex/erp-analytics-profit-creator-workflow-20260820`。
- 功能实现与生产部署基线提交：`f5f28865f9311ad8749f1e77e83ab690f3eb30cd`；交接文件提交后的最新 HEAD 应通过 Git/GitHub 重新读取。
- Pull Request：[#16](https://github.com/kevindongbo/codex/pull/16)。
- PR 状态：Open、Draft、未合并；功能实现验收时 head 为上述基线 SHA，交接文件 Push 后会产生新的 head SHA。
- PR base 当时为 `codex/erp-production-regression-fix-20260813`，不是 `main`。这是为了保留未合并的前序功能链；不要擅自改 base 或从旧 `main` 重做。

以上信息在新对话中必须重新检查 GitHub。

## 7. 禁止提交到 GitHub 的内容

以下内容不得记录到本文件、提交到 GitHub、写入前端或出现在日志/PR 中：

- 密码、Token、GitHub Token。
- 阿里云 AccessKey、Secret、ACR 密码。
- SSH 私钥、服务器密码、数据库密码。
- 生产环境 `.env` 及其完整内容。
- 真实用户数据和生产数据导出。
- 数据库备份、原始业务 Excel。
- 临时调试文件、缓存、依赖缓存、大型日志。
- 无关截图或包含敏感信息的配置和截图。

如发现疑似敏感信息，应停止提交，先明确提醒并缩小暂存范围。占位符统一使用类似：

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

## 8. 阿里云服务器和部署架构

### 8.1 当前生产架构（已确认）

- **用途**：东铂跨境 ERP 生产站点。
- **阿里云地区**：华南 3（广州）。
- **操作系统**：Ubuntu 22.04 64 位。
- **服务器规格记录**：2 vCPU / 4 GiB；属于动态资源信息，使用前应在控制台核验。
- **生产域名**：`dongbokeji.com`、`www.dongbokeji.com`。
- **项目目录**：`/opt/dongbo/app`。
- **后端目录**：`/opt/dongbo/app/backend`。
- **Python 虚拟环境**：`/opt/dongbo/venv`。
- **备份目录**：`/opt/dongbo/backups`。
- **生产环境文件**：`/opt/dongbo/app/.env`；只能在服务器使用，禁止读取回传、覆盖或提交。
- **数据库**：服务器 PostgreSQL，数据库名 `dongbo_erp`。
- **应用服务**：`dongbo-erp.service`。
- **应用进程**：Gunicorn，监听 `127.0.0.1:8000`。
- **反向代理与静态站点**：Nginx。
- **本地健康检查**：`http://127.0.0.1:8000/api/health/`。
- **公网健康检查**：`https://dongbokeji.com/api/health/`。
- **网页检查**：`https://dongbokeji.com/`。
- **服务日志**：`journalctl -u dongbo-erp.service`。
- **Nginx 日志**：通常在 `/var/log/nginx/`，具体文件名需要服务器核验。

生产服务器 IP 不写入长期记忆；登录时使用 `<ALIYUN_SERVER_IP>` 并在阿里云控制台核验。

### 8.2 ACR、镜像和 Docker 状态

当前生产不是 Docker/Compose，也没有已确认的 ACR 发布链路。生产前后端不是两个已确认的 ACR 镜像。以下信息均为 **待确认**，不得猜测：

- ACR Registry 地址与地区。
- ACR 命名空间与镜像仓库名称。
- 前端镜像、后端镜像与标签规则。
- 生产 Docker Compose 文件位置、容器名称和服务名称。
- 生产 Redis 服务。

仓库根目录虽然存在 `docker-compose.yml`，其服务为 `db`、`api`、`caddy`，并包含 PostgreSQL 16、Django API 和 Caddy；这是代码仓库支持的本地/备用容器方式。除非服务器实际架构已变更并得到真实输出确认，否则不要把它当作当前生产部署方式，也不要生成虚构的 ACR 登录和拉镜像命令。

### 8.3 最近一次生产状态快照（需要结合服务器核验）

2026-08-21 的真实服务器输出显示：

- 部署分支为 `codex/erp-analytics-profit-creator-workflow-20260820`。
- 部署 SHA 为 `f5f28865f9311ad8749f1e77e83ab690f3eb30cd`。
- 迁移 `erp.0033_analytics_profit_creator_workflows` 和 `erp.0034_creator_attribution_unattributed` 已应用。
- `dongbo-erp.service` 为 active (running)。
- Nginx 配置检查通过并处于 active。
- 本地和公网健康检查返回 `{"status":"ok","database":"ok"}`。
- 服务器最终输出 `DEPLOY SUCCESS`。

这是时间点快照，不代表未来仍然不变。PR 描述可能仍保留部署前的旧表述，应以服务器真实输出和最新 GitHub 状态为准。

## 9. 阿里云终端更新命令

用户的默认习惯是：Codex 完成修改、测试、Commit、Push 和 Draft PR 后，不直接登录阿里云部署，而是提供一整段可复制到服务器黑色终端执行的 Bash。命令中的 `<TARGET_BRANCH>`、`<FINAL_HEAD_SHA>` 和 `<PREVIOUS_HEAD_SHA>` 必须替换成当次最终真实值。

### 9.1 当前生产架构的标准更新模板

```bash
set -euo pipefail

APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
SERVICE=dongbo-erp.service
TARGET_BRANCH='<TARGET_BRANCH>'
EXPECTED_SHA='<FINAL_HEAD_SHA>'
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="/opt/dongbo/backups/deploy-$TS"

cd "$APP"
echo '=== 部署前状态 ==='
git status --short
git branch --show-current
git rev-parse HEAD

if [ -n "$(git status --porcelain)" ]; then
  echo 'ERROR: 服务器工作区有未提交改动，停止部署，禁止覆盖。'
  exit 1
fi

mkdir -p "$BACKUP"
git rev-parse HEAD > "$BACKUP/previous-head.txt"
sudo -u postgres pg_dump -Fc dongbo_erp > "$BACKUP/dongbo_erp.dump"
echo "Backup: $BACKUP"

git fetch origin "$TARGET_BRANCH"
git checkout "$TARGET_BRANCH"
git pull --ff-only origin "$TARGET_BRANCH"

ACTUAL_SHA=$(git rev-parse HEAD)
echo "Expected SHA: $EXPECTED_SHA"
echo "Actual SHA:   $ACTUAL_SHA"
test "$ACTUAL_SHA" = "$EXPECTED_SHA"

"$VENV/bin/python" -m pip install -r backend/requirements.txt
"$VENV/bin/python" backend/manage.py check
"$VENV/bin/python" backend/manage.py makemigrations --check --dry-run
"$VENV/bin/python" backend/manage.py migrate --noinput
"$VENV/bin/python" backend/manage.py collectstatic --noinput

sudo nginx -t
sudo systemctl restart "$SERVICE"
sudo systemctl reload nginx
sudo systemctl is-active "$SERVICE"
sudo systemctl is-active nginx
sudo systemctl status "$SERVICE" --no-pager -l

echo '=== 本机后端健康检查 ==='
curl -fsS http://127.0.0.1:8000/api/health/
echo

echo '=== 通过本机 Nginx 检查 HTTPS ==='
curl -fsS --resolve dongbokeji.com:443:127.0.0.1 https://dongbokeji.com/api/health/
echo
curl -fsSI --resolve dongbokeji.com:443:127.0.0.1 https://dongbokeji.com/

echo '=== 正常公网检查（依赖服务器 DNS） ==='
curl -fsS https://dongbokeji.com/api/health/
echo
curl -fsSI https://dongbokeji.com/

echo '=== 最近日志 ==='
sudo journalctl -u "$SERVICE" -n 100 --no-pager

echo 'DEPLOY SUCCESS'
echo "Branch: $TARGET_BRANCH"
echo "SHA:    $ACTUAL_SHA"
echo "Backup: $BACKUP"
```

如果公网域名检查因服务器 DNS 临时失败，但本机后端和 `--resolve` 检查通过，只能说明应用与本机 Nginx 正常；仍需排查 DNS 并再次取得公网健康检查成功输出，不能忽略错误后直接宣称全部成功。

### 9.2 应用代码回滚模板

优先回滚应用代码，保留部署前数据库备份。数据库迁移是否需要反向执行，必须先核对 migration 的可逆性和数据影响，不自动恢复整库。

```bash
set -euo pipefail

APP=/opt/dongbo/app
VENV=/opt/dongbo/venv
SERVICE=dongbo-erp.service
ROLLBACK_SHA='<PREVIOUS_HEAD_SHA>'
TS=$(date +%Y%m%d-%H%M%S)
ROLLBACK_BACKUP="/opt/dongbo/backups/pre-rollback-$TS"

cd "$APP"
if [ -n "$(git status --porcelain)" ]; then
  echo 'ERROR: 服务器工作区有未提交改动，停止回滚。'
  exit 1
fi

mkdir -p "$ROLLBACK_BACKUP"
git rev-parse HEAD > "$ROLLBACK_BACKUP/current-head.txt"
sudo -u postgres pg_dump -Fc dongbo_erp > "$ROLLBACK_BACKUP/dongbo_erp.dump"

git fetch origin
git cat-file -e "$ROLLBACK_SHA^{commit}"
git checkout --detach "$ROLLBACK_SHA"
test "$(git rev-parse HEAD)" = "$ROLLBACK_SHA"

"$VENV/bin/python" -m pip install -r backend/requirements.txt
"$VENV/bin/python" backend/manage.py check
"$VENV/bin/python" backend/manage.py migrate --noinput
"$VENV/bin/python" backend/manage.py collectstatic --noinput

sudo nginx -t
sudo systemctl restart "$SERVICE"
sudo systemctl reload nginx
sudo systemctl is-active "$SERVICE"
curl -fsS http://127.0.0.1:8000/api/health/
echo
curl -fsS --resolve dongbokeji.com:443:127.0.0.1 https://dongbokeji.com/api/health/
echo

echo 'ROLLBACK APPLICATION SUCCESS'
echo "SHA:    $(git rev-parse HEAD)"
echo "Backup: $ROLLBACK_BACKUP"
echo '注意：当前为 detached HEAD；下一次部署应重新 checkout 正确功能分支。'
```

如果确认必须恢复数据库，应先停止应用、再对当前数据库做一次备份，并使用当次部署产生的精确 `.dump` 文件。整库恢复会覆盖部署后的新数据，属于高风险破坏性操作，必须获得用户明确授权后再生成和执行精确命令。

### 9.3 常用只读诊断命令

```bash
cd /opt/dongbo/app
git status --short
git branch -vv
git log --oneline --decorate -20
git reflog -20
git rev-parse HEAD

sudo systemctl status dongbo-erp.service --no-pager -l
sudo journalctl -u dongbo-erp.service -n 200 --no-pager
sudo nginx -t
sudo systemctl status nginx --no-pager -l

/opt/dongbo/venv/bin/python backend/manage.py check
/opt/dongbo/venv/bin/python backend/manage.py showmigrations erp

curl -fsS http://127.0.0.1:8000/api/health/
curl -fsS --resolve dongbokeji.com:443:127.0.0.1 https://dongbokeji.com/api/health/
curl -fsSI --resolve dongbokeji.com:443:127.0.0.1 https://dongbokeji.com/
```

## 10. 当前项目状态

### 10.1 需要结合仓库核验的当前开发快照

- 当前主要模块：数据分析、利润配置与保存、达人管家、调拨终结和智能补货 UI/口径。
- 功能分支：`codex/erp-analytics-profit-creator-workflow-20260820`。
- 功能实现与生产部署基线：`f5f28865f9311ad8749f1e77e83ab690f3eb30cd`；当前分支最新 HEAD 需要从仓库重新核验。
- Draft PR：[#16](https://github.com/kevindongbo/codex/pull/16)，尚未合并。
- 数据库迁移：`0033_analytics_profit_creator_workflows`、`0034_creator_attribution_unattributed`。
- 当前提交链包含前序 ERP UI、库存订单流程和生产回归修复，不应从旧 `main` 重做。

### 10.2 已完成测试快照

在上述 SHA 对应的本地验收中：

- `python backend/manage.py check`：通过。
- `python backend/manage.py makemigrations --check --dry-run`：通过。
- `python backend/manage.py test apps.erp.tests --noinput`：161 项通过。
- `node --check app.js`、`team.js`、`profit-calculator.js`：通过。
- `tests/site.test.mjs`：18 项通过。
- `tests/domain.test.mjs`：17 项通过。
- `tests/team.test.mjs`：25 项通过。
- 前端合计 60 项通过。
- `node scripts/build-site.mjs`：通过。
- Playwright：智能补货表头粘性定位通过；利润配置自动保存/F5、临时 SKU 隔离、方案保存/重开/重算/新版本/另存为链路通过。
- 迁移 0033 到 0034 的实际应用验证通过。

这些是历史测试输出，新任务修改后必须重新运行适用测试。

### 10.3 当前已知注意事项

- 历史上已经处于“部分收货”的调拨不会被迁移自动结束；用户需要在 UI 中执行“结束调拨”，系统才会将余量异常关闭。这是避免擅自改动历史业务数据的设计。
- 工作区可能存在大量用户自己的未跟踪目录、缓存、历史材料和 worktree。不要删除、覆盖或全量暂存。
- PR #16 的 base 是前序功能分支；在合并链未变化前，不要擅自改为旧 `main`。
- 生产部署已在 2026-08-21 有成功输出，但新对话仍需核验当前服务器 SHA、服务状态、迁移和公网健康。
- ACR 与生产 Docker 信息没有确认；不得把仓库 Compose 文件误当成当前生产事实。

### 10.4 新 Codex 接手后的第一步

1. 阅读本文件、`AGENTS.md` 和 `agent-memory/INDEX.md`。
2. 执行 `git status --short`、`git branch -vv`、`git log --oneline --decorate -20`、`git reflog -20`。
3. 核验当前 HEAD、目标功能分支、远端跟踪和是否有未推送代码。
4. 核验 PR #16 或用户指定的新 PR 的 head/base/Draft/CI/merge 状态。
5. 阅读用户当次指定的 `requirements/.../01_REQUIREMENTS.md` 及关联交接文件。
6. 只读取任务相关代码和测试后再修改。

### 10.5 最容易误改的功能

- 库存流水、调拨在途、采购在途和异常关闭之间的数量关系。
- 订单整单锁库、换仓失败回滚、取消释放和人工恢复履约。
- 销售日均出库的原销售日、退货冲减和排除类型口径。
- 利润 working config 与临时试算输入、正式策略、版本化保存之间的边界。
- 店铺状态在 `emptyState()` / `normalizeV5()` / `adaptState()` 间的字段保留。
- 组织级、店铺级权限和达人归因数据范围。

## 11. 完成任务后的固定汇报格式

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

如果有迁移，应将“本次无数据库迁移”替换为精确迁移文件、备份方式、应用命令、验证结果和回滚影响。若用户当次要求更具体的字段或逐项 PASS/FAIL 验收，以用户当次格式为准。
