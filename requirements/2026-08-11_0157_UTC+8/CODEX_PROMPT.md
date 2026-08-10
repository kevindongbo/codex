# Codex 调用提示词

请在 GitHub 仓库 `kevindongbo/codex` 中完整实施需求 `ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-01`。

## 固定输入

- 需求上传时间：`2026-08-11 01:57（UTC+8）`
- 需求分支：`docs/erp-replenishment-intransit-store-20260811-0157`
- 需求目录：`requirements/2026-08-11_0157_UTC+8/`
- 完整需求：`requirements/2026-08-11_0157_UTC+8/ERP_REPLENISHMENT_INTRANSIT_STORE_REQUIREMENTS.md`
- 部署交接：`requirements/2026-08-11_0157_UTC+8/DEPLOYMENT_HANDOFF.md`
- 代码审计参考：`main` @ `3353edaaa4dce8ca44e8da729f22e3800aafa570`
- **实际实施继承基线**：`codex/implement-profit-strategy-ui-fixes-20260805` @ `63cad114ef9567ad40a1c9001b81261fedf830cc`（Draft PR #10 HEAD）
- 新实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 实施 PR 目标分支：`codex/implement-profit-strategy-ui-fixes-20260805`

## 1. 开始前必须做

1. 拉取远端最新 refs，确认精确基线 SHA `63cad114ef9567ad40a1c9001b81261fedf830cc` 可解析。
2. 从需求分支读取本目录下的 README、完整需求和部署交接文件。
3. 不要只依据 main 的旧代码结论；对实际实施基线重新审计相关代码。
4. 重点检查：
   - `backend/apps/erp/models.py`
   - `backend/apps/erp/replenishment.py`
   - `backend/apps/erp/services.py`
   - `backend/apps/erp/serializers.py`
   - `backend/apps/erp/views.py`
   - `backend/apps/erp/urls.py`
   - `backend/apps/erp/integrations.py`
   - `backend/apps/erp/tests/`
   - `app.js`
   - `team.js`
   - `index.html`
   - `styles.css`
   - `tests/*.test.mjs`
5. PR #10 继承链如果已经存在 `OwnStore / StoreProduct / 利润策略 / 权限` 等功能，必须演进复用，不允许平行再建第二套模型，也不能删掉与本需求无冲突的既有功能。
6. 如果旧实现与本需求文档冲突，以本需求文档为最终验收标准。

## 2. Git 操作

不要直接在需求分支、main 或旧实施分支上修改。

从精确 SHA：

`63cad114ef9567ad40a1c9001b81261fedf830cc`

创建并切换到：

`codex/implement-erp-replenishment-intransit-store-20260811`

所有代码、migration、测试与必要部署文档都提交到此实施分支。

## 3. 必须实施的业务范围

完整实现需求文档全部条款，尤其：

- 同内部 SKU 跨仓库、跨平台、跨店铺统一净销量；
- 只统计真实销售订单实际出库，手动出库/调拨/调整等不能算销量；
- 退货回溯原销售日期冲减净销量；
- 保留现有后端 3/7/15/30 权重以及波动、安全库存、MOQ、pack 等算法；
- `总备货时效 + 覆盖天数` 作为唯一需求周期；
- SKU×仓库覆盖值优先于仓库默认，缺参数不计算；
- SKU×仓库智能补货启用开关；
- 库存拆分：现货、锁定、可用、已采购待发货、已确认在途；
- 采购：发货批次 → 多物流包 → 包内 SKU；独立确认本批发货；分批收货；在途异常关闭；关闭未发货；历史迁移；
- 调拨：创建即预占；多物流包；整单确认发货；部分收货；异常关闭；确认发货后禁止直接取消；历史在途迁移；
- 订单允许暂不选仓；人工选仓立即整单锁库；出库前可事务化换仓；不自动拆仓、不自动选仓；
- 所有平台都允许手工创建独立 ERP 店铺；market 可空；同组织店铺名唯一；
- TikTok 授权和店铺资料分离；从已有 ERP 店铺发起授权；一次 OAuth 返回多店时人工只选一个绑定；旧授权迁移；
- 外部 SKU 未映射订单仍同步，映射后回填最近 30 天销量；
- 补货建议持久化，允许人工修改、分次转采购；按“目的仓 + 供应商”生成采购草稿。

## 4. 硬性禁止

- 不得修改后端现有 3/7/15/30 销量权重。
- 不得把统一销量按仓库占比分摊。
- 不得把手动出库算销售。
- 不得把“已下单未发货”算在途。
- 不得自动选择仓库或拆仓。
- 不得让 TikTok OAuth 自动批量创建 ERP 店铺。
- 不得静默删除、覆盖或重写历史库存/采购/调拨/授权记录。
- 不得静默修改店铺名称解决迁移冲突。
- 不得通过写死业务数字或削弱测试来过验收。
- 不得直接部署生产。
- 不得自动 merge PR。

## 5. 数据迁移

必须生成正式 Django migration，并实现兼容/数据迁移逻辑。

至少验证：

- 旧采购物流不会因升级突然丢失在途；
- 旧 IN_TRANSIT 调拨不会重复扣来源库存或丢失目标在途；
- 旧 review cycle 正确迁移为 coverage 初始值；
- 旧 TikTokShopConnection 的 token、shop_id、open_id、sync history 不丢；
- 若实施基线已有 OwnStore，直接演进该模型；
- 店铺名称冲突明确报错/迁移报告，不静默改名；
- `target_days` 不再形成第二套需求周期。

## 6. 并发、幂等、审计

库存和状态机动作必须使用 `transaction.atomic`、必要的 `select_for_update`、幂等键/唯一约束。

并发情况下必须防止：

- 超卖；
- 重复发货；
- 重复收货；
- 重复异常关闭；
- 同一补货建议重复/超量转采购。

需求文档指定的业务动作必须写 `AuditLog`，保留 before/after 或足够还原事实的摘要。

## 7. 前端要求

同步修改团队模式和本地模式的必要 UI/API adapter。

特别处理当前本地前端存在的另一套补货计算公式：最终不得继续出现与后端 3/7/15/30 规则冲突的 7/15/30 `0.5/0.3/0.2` 业务口径。

库存列表、采购、调拨、智能补货、订单、店铺页面均需支持需求文档规定的字段和操作。

## 8. 自动化测试

先确认项目现有准确命令，然后至少执行：

- `python backend/manage.py check`（或项目实际等价命令）
- `python backend/manage.py makemigrations --check --dry-run`
- ERP Django 全量测试
- 新增补货、采购、调拨、订单、店铺/TikTok 定向测试
- `node --check app.js`
- `node --check team.js`
- 其它实际修改 JS 的语法检查
- `node --test tests/*.test.mjs` 或项目实际完整前端测试
- 项目实际 build 命令
- `git diff --check`

需求文档“关键验收测试 A-O”必须有自动化测试覆盖或明确的等价覆盖证据。

测试失败不能隐藏。先修复再提交；若属于既有环境问题，记录原始错误、处理方式和最终结果。

## 9. GitHub 交付

代码完成后：

1. 提交所有代码、migration、测试和必要文档。
2. 将 `codex/implement-erp-replenishment-intransit-store-20260811` 推送到 GitHub。
3. 创建 **Draft PR**，目标分支：`codex/implement-profit-strategy-ui-fixes-20260805`。
4. PR 标题：`ERP-REPLENISHMENT-INTRANSIT-STORE-20260811: 统一销量补货、在途物流与店铺授权分离`
5. PR body 必须写明：
   - 需求编号；
   - 需求上传时间；
   - 实施基线分支和精确 SHA；
   - 最终实施 HEAD SHA；
   - 修改模块/文件；
   - migrations；
   - 数据迁移策略；
   - 测试命令和结果；
   - 已知风险；
   - 回滚说明；
   - `未自动合并、未部署生产`。

## 10. 阿里云部署交接

代码完成后不要连接或部署阿里云。

按照 `requirements/2026-08-11_0157_UTC+8/DEPLOYMENT_HANDOFF.md` 汇总真实部署事实，并新增/更新：

`docs/deployment/aliyun/ERP-REPLENISHMENT-INTRANSIT-STORE-20260811.md`

必须明确：

- final HEAD SHA；
- migration 文件；
- 是否需要依赖安装；
- 是否需要 build；
- 是否需要 collectstatic；
- 是否新增环境变量（只列变量名，不写密钥）；
- 是否改 Docker/Caddy/Nginx/systemd；
- 实际需要重启/重载的服务；
- 健康检查；
- smoke tests；
- 数据库回滚风险。

**不要猜生产目录、数据库名、数据库账号、systemd 服务名。** 能从仓库现有部署文档确认就使用真实值；不能确认就明确标记无法确认。

## 11. 最终回复格式

只有在确认代码已经推送 GitHub 后才报告：

- Implementation branch
- Draft PR URL / number
- Final HEAD SHA（40 位）
- Migrations
- Tests passed / failed
- Deployment-impact summary
- Rollback-impact summary
- Remaining risks

最后明确写：

`代码已推送 GitHub；未自动合并；未部署生产。`