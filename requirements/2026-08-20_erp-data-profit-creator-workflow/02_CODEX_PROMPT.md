# 给 Codex 的实施提示词

请打开 GitHub 仓库 `kevindongbo/codex`，实施以下需求包：

```text
requirements/2026-08-20_erp-data-profit-creator-workflow/00_README.md
requirements/2026-08-20_erp-data-profit-creator-workflow/01_REQUIREMENTS.md
requirements/2026-08-20_erp-data-profit-creator-workflow/02_CODEX_PROMPT.md
```

以 `01_REQUIREMENTS.md` 为最终业务验收标准。

## 一、开始前

1. 完整阅读项目长期记忆、根目录和适用子目录的 `AGENTS.md`。
2. 按 `agent-memory/INDEX.md` 只读取本任务相关主题。
3. 核对交接文档、旧需求和当前代码；真实状态优先。
4. 执行：

   ```bash
   git status --short
   git branch -vv
   git log --oneline --decorate -20
   git reflog -20
   git remote -v
   ```

5. 检查 GitHub 分支与 Draft PR #15；不要覆盖未提交、未推送或未合并的已有代码。
6. 以已部署基线 `eebdbfcbf033c74f8f2d82e8204336c08834c394` 或实施时确认的最新后继提交为起点，创建：

   ```text
   codex/erp-analytics-profit-creator-workflow-20260820
   ```

7. 不直接修改或合并 `main`，不自动部署生产。

## 二、必须先完成代码审计

阅读本任务涉及的：

- `StockTransfer`、调拨行、物流包、收货与异常关闭服务；
- 在途汇总、库存序列化和智能补货算法；
- 智能补货前端渲染、表头固定与浏览器事件；
- OwnStore、订单、出库、退货、竞品模型和现有数据页面；
- 利润配置、working config、命名策略、计算器、序列化器和前端初始化；
- 权限、路由、审计日志和现有测试。

已经正确的能力直接复用，不创建第二套 Store、StockTransfer、库存余额、竞品或利润策略。

## 三、实施范围

严格完成七项：

1. 部分收货调拨增加明确“结束调拨”，后端加锁重算并一次异常关闭所有剩余量；按请求键幂等，把剩余从在途移除。
2. 智能补货表头随页面滚动固定，横向同步，商品列正确对齐。
3. 删除“查看补货参数”，周期明细展示所有有权仓库近 7 天订单出库、手动出库、退货冲减、净销量和日均。
4. 将“竞品监控”升级为“数据分析”，包含经营总览、店铺分析、商品/SKU 分析和现有竞品分析。
5. 增加全局及 SKU 覆盖广告返点，严格使用 `USD_PER_MYR`、`null`/显式 `0` 语义和后端 Decimal 计算真实 ROI/CPA；真实定位并修复配置/策略刷新丢失及多人覆盖。
6. 新增允许资料不完整保存的达人管家，包含合作、寄样、内容、跟进和可靠归因。
7. 新增商品利润表；批次包含多个单 SKU 方案，每方案主表一行并显示最新不可变版本，支持复现历史、按当前规则重算和另存为新方案。

## 四、数据与安全

- 新模型和字段提供 migration。
- migration 不伪造历史 GMV、达人或利润数据。
- 调拨短少进入 `exception_closed_quantity`，不能进入 `received_quantity`。
- 新 analytics、达人和利润记录权限必须复用现有能力体系并同时约束 GET 与写请求；无权接口返回 403。
- 商品利润保存接口不得信任浏览器回传的金额结果，必须在后端事务内重算或验证不可篡改计算令牌。
- 数据库修复或部署迁移前必须备份，并给出验证和回滚方式。
- 不泄露或提交密码、Token、私钥、AccessKey、数据库密码或生产 `.env`。
- 不抓取未授权卖家后台，不猜测金额或达人归因。

## 五、测试

先写失败回归测试，再修代码。至少实际运行：

```bash
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test apps.erp.tests --noinput

node --check app.js
node --check team.js
node --check profit-calculator.js

node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs

node scripts/build-site.mjs
git diff --check
```

还必须用可控浏览器验证：

- 1440×900 视口下智能补货页面纵向/横向滚动后的表头和商品列位置，边界误差不超过 2 px；
- 两个独立登录会话验证 working config 自动保存、F5、同组织共享和乐观锁冲突；
- 利润计算、广告返点、保存到商品利润表、重开、修改、重算、新版本；
- 达人资料只填写昵称也能保存；
- 部分收货调拨结束后在途、状态和库存同步更新。

不得虚构测试结果，不得用源码正则测试代替真实前端链路。

## 六、GitHub 交付

测试通过后：

1. 检查 `git status` 和 `git diff --stat`。
2. 只暂存本任务相关文件，不使用会误纳入既有未跟踪文件的宽泛暂存命令。
3. Commit 建议：

   ```text
   feat(erp): add analytics creator management and saved profit workflows
   ```

4. Push 到 `codex/erp-analytics-profit-creator-workflow-20260820`。
5. 创建一个可审查的 Draft Pull Request，base 使用实施时确认的已部署功能分支；不得自动 merge。
6. PR 写明迁移、测试、浏览器验收、历史调拨数据处理、部署影响和回滚影响。

## 七、最终回复

使用 `01_REQUIREMENTS.md` 第 15 节格式，并逐项报告七项 PASS/FAIL。只要生产数据修复、真实浏览器链路或关键测试未完成，必须明确标为未验证，不能写“全部完成”。

阿里云命令必须在最终精确 Commit SHA 确定后，根据仓库和服务器真实配置生成一整段可复制 Bash；未经用户明确授权不得执行生产部署。
