# 代码事实审计与需求追踪

审计基线见 [README](README.md)。以下是静态代码和既有测试内容的审计，**本轮没有重新运行历史功能测试或登录生产后台**。行号指该基线；后续实现变更后以符号定位。

## 1. 账号完整调用链

`index.html` 账号管理面板 → `app.js:1117 renderInternalAccountManager()`、`openInternalAccountManager()`、账号行 click → `team.js:363 listInternalAccounts()`、`updateInternalAccount()` → `/api/internal-accounts/` 及 `/<membership UUID>/` → `views.py:628 internal_accounts()`、`:689 internal_account_detail()` → `InternalAccountSerializer` → Django User、Membership、仓库授权 → AuditLog／同步版本 → GET 列表回显。

| 事实 | 证据 | 对需求的影响 |
| --- | --- | --- |
| 主账号可新建、编辑、启用／停用子账号 | `_require_owner()`；`InternalAccountSerializer`；前端 edit/toggle 按钮 | 不重建第二套账号体系，新增离职生命周期 |
| 当前 DELETE 并非物理删除 | `internal_account_detail()` 的 DELETE 设置 `membership.active=False` 与 `user.is_active=False`，审计 `account.disable`，返回204 | 不能复用 DELETE 的文案冒充已离职归档，也不能更改老客户端的停用含义 |
| 列表没有离职筛选 | GET 查询组织全部 Membership；payload 只有 active，没有 departure 字段 | 停用后仍挤在日常列表，这是截图对应的已实现但需修改之处 |
| 前端没有归档入口 | `renderInternalAccountManager()` 仅编辑和启用／停用；网关 `disableInternalAccount()` 仍为 DELETE | 加入已离职标签页、确认步骤与恢复入口 |
| 账号管理后端仅主账号 | `_require_owner()` 使用 `is_owner()`，定义为已认证超级用户 | “管理员”角色不是主账号，不能因 UI 改动扩大权限 |
| 另一组 Membership 接口不能直接删除 | `MembershipViewSet:1294` 的 `http_method_names` 为 get/head/options | 不能只看到 `perform_destroy()` 就认定可用的删除接口 |
| 停用后旧 access 会被拦截 | `permissions.py:request_organization()`、`authentication.py`；既有 `test_owner_manages_internal_accounts_and_child_logs_in_directly` | 已有测试覆盖停用时旧 access 401、新登录401；没有证明恢复后旧 token 永久失效 |
| refresh 使用通用 SimpleJWT 视图 | `backend/config/urls.py:10`；`team.js:247 refreshAccessToken()` | 归档与恢复必须同时检查 access 和 refresh 的代际，不能只禁登录表单 |
| 角色权限空列表会继承角色默认 | `permissions.py:membership_permissions()`；admin 默认有全目录权限 | 恢复不能简单清空 permissions 却保留 admin，从而意外恢复高权限 |
| 新采购人员下拉仅查启用人员 | `views.py:758 purchase_members()` | 归档要继续排除新选择，但历史采购人不得丢失或被替换 |
| 排班区分当前可用人员与已开始历史格 | `scheduling_views.py:board()` 的 enabled、started 分支 | 归档应隐藏未来安排和待提交提醒，同时保留过去归属 |
| User 关联有 PROTECT 和 SET_NULL 混合 | `scheduling_models.py` owner/actor；`models.py:PurchaseOrder.purchaser`、AuditLog.actor、ProfitPlanVersion.created_by | 直接删除会破坏追踪或被外键拒绝；本期不做物理删除 |

## 2. 利润完整调用链

`index.html:#profitCountry`、SKU 输入及三级类目 → `profit-calculator.js:loadStaticConfig()`／`loadWorkingConfig()`／`calculate()` → `/api/profit-calculator/config/`、`working-config/`、`exchange-rates/`、`calculate/` → `ProfitCalculationSerializer` → `calculate_profit()` → 马来西亚类目与物流规则 → 结果展示。保存走 `ProfitPlanViewSet` → `profit_records.py:98 save_profit_batch()` → 服务端权威汇率重算 → batch／plan／不可变 version → 回读历史。

商品列表另有链路：`app.js` 商品编辑 → `team.js:saveProduct()` → SKU 的 `store-products` 批量保存 → `SKUViewSet` 的利润摘要 → `normalizeProduct` 保留利润字段 → 列表展开。因此国家扩展必须覆盖商品列表，不只独立利润页。

| 事实 | 证据 | 缺口 |
| --- | --- | --- |
| 后端只接受 MY | `profit_serializers.py:ProfitCalculationSerializer.country` 和 `serializers.py:ProfitCalculationStrategyConfigSerializer.country` 都只列 MY | 只加 HTML 的 US/MX option 会被后端拒绝 |
| 配置接口仅返回马来西亚 | `views.py:224 profit_calculator_config()` | 无 country-scoped 类目、币种、规则版本和履约能力 |
| 当前规则是 MY 专用 | `profit_calculator.py` 的 MY RULE_VERSION、BXP、LVG、交易费、支持费；`profit_shipping_rates.py` | US/MX 不能继承 MY 费项与有效期 |
| 本土发货当前尾程为0 | 计算器 seller_type local 分支 | 与新需求中的当地仓付费履约冲突，MY 兼容行为另保留 |
| 重量按 MY 10g 进位，上限30000g | `ProfitItemSerializer.validate_weight_g()`、`malaysia_cross_border_shipping()` | US lb/oz、尺寸／体积重、MX区域价与上限需要独立验证 |
| 只暴露箱包及美妆个护三级树 | `profit_category_taxonomy.py`、`category_tree()` | 没有本期 US/MX 安防、监控和门铃的国家类目映射 |
| 前端本位币和文字固定 MYR | `profit-calculator.js:displayCurrency`、MYR/CNY/USD切换；index heading/table | US要USD，MX要MXN；只改“售价”标签会错误解释金额 |
| 共享配置每组织只有一条 | `ProfitCalculationWorkingConfig` 的 organization 唯一约束 | 两个成员切不同国家会互相覆盖，需按国家隔离及独立revision |
| 策略名和默认策略只按组织唯一 | `ProfitCalculationStrategy` 的组织+name及组织默认唯一 | 同名“默认策略”在三国必须可并存，默认也分国 |
| 汇率数据结构固定 MYR→CNY/USD | `ExchangeRateSnapshot`、`exchange_rates.py` | 增加币对／市场作用域；不能把 MXN 当 MYR 或用倒数混写 |
| 店铺售价字段明确叫 sale_price_myr | `models.py:213 StoreProduct`、serializer、SKU列表利润 | 新增本位售价和币种，迁移保留原 MYR 语义 |
| SKU 只有单一 category_code 和包装重量 | `models.py:172 SKU` | 新增分市场类目映射及包装尺寸，不能用换国家覆盖原类目 |
| 历史利润已保留快照与规则版本 | `ProfitPlanVersion`、`profit_records.py` | 可复用；新增国家、税务、报价、物流分摊、规则哈希，不改旧快照 |
| 当前 calculate 与保存的汇率信任边界不同 | `profit_calculator_calculate()` 接收验证输入直接计算；`save_profit_batch()` 重取权威配置／汇率 | v2 计算和保存统一 resolver，禁止预览与落库用不同国家／版本 |
| 截图的失败消息包括登录已过期 | `profit-calculator.js:579 strategyFailure()`、`:726 loadConfig()` | 先验证401恢复；无法凭截图认定基础佣金表损坏，不允许错误时悄悄用固定默认费率 |

## 3. 需求完成度

| 编号 | 用户目标 | 状态 | 差距与初步方案 | 验证 |
| --- | --- | --- | --- | --- |
| A-01 | 新建／编辑／停用账号 | 已完成 | 保留；本轮静态审计，生产未验证 | 回归创建、编辑、角色和仓库权限 |
| A-02 | 移除日常列表中的离职人员且可恢复 | 未完成 | 增加就业状态、归档元数据、筛选与恢复 | 账号生命周期及旧记录断言 |
| A-03 | 离职立即失去访问，恢复后不复活旧会话 | 部分完成 | 停用已有；增加 token generation 与 refresh 检查 | 真实JWT跨归档／恢复测试 |
| P-01 | 切换 MY/US/MX 自动换规则 | 未完成 | 分国能力、配置、缓存、币种和规则 resolver | 国家快速切换及并发测试 |
| P-02 | 当地仓多履约及头程单列 | 未完成 | 包裹报价、服务资格、成本拆解 | 重量/尺寸/区域/数量边界 |
| P-03 | US/MX 3C摄像头 | 未完成 | 操作类目与官方类目ID、收费组分离 | 错国类目拒绝、规则来源可追踪 |
| P-04 | 保存利润方案和历史回读 | 已实现但需要修改 | 复用不可变快照，扩充market context与schema版本 | 老MY结果逐分不变，新版本可复现 |
| P-05 | 商品店铺售价和列表利润 | 已实现但需要修改 | 既有MY链路扩展到多市场，禁止混币区间 | 同SKU三国多店保存／回读 |

## 4. 不能由本轮审计推出的结论

不能声称生产人员已归档；不能声称 US/MX 已可计算；不能把任意图片上的 6% 当作所有类型永久费率；不能把页面打开或全部单元测试通过当作卖家物流资格、税务身份或真实结算对账已通过。后续验收依 [验收计划](06_ACCEPTANCE_ROADMAP.md)执行。
