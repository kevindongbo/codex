# 数据契约、接口、迁移与回滚设计

本文件是后续实现建议，当前没有生成或执行迁移。具体迁移编号必须在实施时按最新迁移图分配，不能假定上一轮计划的0039已经存在。

## 1. 数据模型建议

### 1.1 账号

| 实体 | 新增／修改 | 约束及默认 |
| --- | --- | --- |
| Membership | employment_status、departed_at、departure_date、departed_by、departure_reason、restored_at、restored_by、revision | status仅employed/departed，旧行employed；revision为正整数、默认1；departed时active必须false；原因仅受控读取 |
| AccountSecurityState（User一对一） | auth_version、requires_password_reset、updated_at | version初始0、只递增；恢复时requires_password_reset=true，主账号成功设置新密码后清除；未清除不得启用；代际不在恢复或回滚时清零，所有签发和刷新路径共享 |
| 既有User | 复用is_active和密码哈希 | 不自建第二套密码，不物理删除；恢复不自动启用 |
| AuditLog | 新account.depart/archive/restore等语义事件，命名实施时统一 | 保留已有account.disable含义；记录对象ID与安全摘要，不记token／密码 |

Membership就业状态不是User全局所属组织模型的替代。当前项目为单内部组织；如果以后支持多组织，需要重新设计全局禁用与组织离职之间关系，不在本期顺手扩展。

### 1.2 市场配置及SKU

| 实体 | 建议字段 | 约束与兼容 |
| --- | --- | --- |
| OwnStore | 规范country_code、currency、seller_program、fulfillment_capabilities、profile_revision；保留原market文本 | MY/MYR、US/USD、MX/MXN组合校验；旧自由文本不能可靠识别的标“待确认” |
| SKU | 保留成本和实物属性；新增包装长宽高、单位；带电属性 | 不覆盖旧category_code，重量继续规范g，尺寸规范cm |
| SKUMarketProfile | organization、sku、country、category_mapping、资格状态、市场达人佣金覆盖 | sku+country唯一；类目必须同国；复制只复制物理信息不复制类目ID |
| StoreProduct | 新price_amount、currency、country；复用sku/store和店铺佣金覆盖 | 仍store+sku唯一；校验与店铺市场币种一致；旧sale_price_myr仅作为MY兼容字段 |
| ProfitCalculationWorkingConfig | 增country，通用汇率引用或手工快照 | 唯一约束从organization改organization+country；revision分国独立 |
| ProfitCalculationStrategy | 增country、revision，config_schema_version | 名称唯一改organization+country+name；每组织每国仅一条default |
| MarketExchangeSnapshot | organization、base_currency、quote_rates(CNY/USD)、effective_at、fetched_at、rate_set_id、source、validation_status、hash | base为本位币；USD/USD=1；一次快照的关联汇率同时有效，不混日期／来源拼接 |
| ProfitPlan/Version/Batch | country、currency、schema_version、context_hash及不可变快照 | 同一plan国家固定；另存到其他国新建plan；旧JSON不破坏性重写 |

旧MY汇率表在兼容期继续读；MY新适配器可封装现有记录，不要求一次删表重建。US/MX解析有自己的校验范围和币种，不能沿用MYR/CNY的固定范围判断MXN。

### 1.3 规则与报价

逻辑实体可采用审核后的版本化JSON文件加数据库发布索引，不强制为每个费率建一张表；但必须满足如下接口与不可变性：

- `MarketRuleBundle`：country、version、hash、effective interval、timezone、source registry、status；内容含fee rules、tax schema、capabilities及引用的category/logistics版本。
- `MarketCategoryMapping`：运营别名与官方原文／leaf_id／祖先路径／fee_group分离；复用版本文件时仍须可按国家稳定定位。
- `LogisticsRateCard`：service/country/seller_program/currency、区域映射、尺寸重量计费、附加费、有效期、included_components和source。官方与商家报价分域，不由普通用户修改公共表。
- `ShippingQuote`：组织、店铺、market、service、packages_hash、region、金额明细、来源版本、valid_until、确认人及不可变hash。人工报价不自动更新其他SKU的报价。
- `TaxProfile`：组织／店铺、国家、主体类型、登记区域、RFC验证状态、税务价格口径、可抵扣性、适用规则引用、revision；不要求在本系统重复存完整证件。

数据库写操作必须检查组织范围和既有权限，新增表不得通过扩大全部数据库或应用权限解决失败。

规则卡内容的最低字段顺序：国家／服务／卖家项目／官方类目或收费组／生效起止与时区／币种／重量单位及进位／尺寸与体积重／起讫区域／基础档和续重价／附加费／含税状态／已包含项目／优惠条件／来源／审核与版本hash。数值缺失保持空并阻止published，不能在模板中以0占位。

## 2. 账号API

保留现有列表、新建、PATCH启停和DELETE停用的兼容语义。新增端点如下，均只有主账号可用：

| 方法与路径 | 行为 | 成功／错误 |
| --- | --- | --- |
| GET `/api/internal-accounts/?employment=employed&active=all&search=...` | 过滤、分页、返回状态数量和revision；默认在职，不返回离职私有原因全文 | 200；403；无效过滤400 |
| GET `/api/internal-accounts/{id}/departure-preview/` | 归档影响摘要及revision，不执行写入 | 200；404；403 |
| POST `/api/internal-accounts/{id}/archive/` | body: revision、departure_date、reason；header: Idempotency-Key | 200归档状态；409版本冲突；400；403 |
| POST `/api/internal-accounts/{id}/restore/` | body: revision、reason；只恢复为在职停用 | 200；409；403 |
| PATCH `/api/internal-accounts/{id}/` | 保留原字段，带revision校验新增的生命周期敏感操作；已离职不能active=true | 200；409 account_departed；400 |

归档/恢复响应至少：id、employment_status、active、revision、departed_at、needs_password_reset、needs_permission_review。reason只向主账号的详情接口返回，不进入采购／排班接口。

幂等域为organization+actor+operation+key，canonical payload hash不含密码；同key同内容返回首次响应，同key不同内容409。组织锁→membership→user→security_state锁顺序固定，事务内完成状态、审计和同步更新。网络超时后客户端复用同key查询／重试，不重新点击生成多个归档事件。

旧DELETE继续只停用，不使employment_status变departed。新离职动作使用archive端点，避免旧浏览器误归档。旧客户端尝试启用已离职用户必须被后端拒绝。

## 3. 多国API（保留v1，新增明确v2契约）

同一路径使用版本前缀`/api/profit-calculator/v2/`。v1无country或country=MY保持现有行为，v1明确传US/MX应400，不静默改成MY。前端三国切换走v2，旧MY浏览器在兼容期可继续v1。

| 方法与路径（v2前缀下） | 输入 | 输出与校验 |
| --- | --- | --- |
| GET `markets/` | 已认证组织 | 可见国家、currency、服务能力及ready/blocked原因，不暴露税号 |
| GET `config/?country=US&as_of=...&store_id=...` | country必须明确；store可选 | 类目、规则包/哈希、费用架构、税务字段、物流能力、有效期、sources；不返回固定MY假配置 |
| GET/PUT `working-config/?country=US` | PUT带revision和config_schema_version | 各国独立revision；409 current_revision；不覆盖别国 |
| GET/POST/PATCH `strategies/` 与 `/{id}/activate/` | country和revision；activate带working_revision | 策略国别不可被PATCH跨国；复制跨国新建；同名各国可并存 |
| GET/POST `exchange-rates/?country=MX` | auto或经授权的手工币对 | 原子rate_set、source、effective/fetched时间、stale；无可用币对503，不补MY |
| POST `shipping-quotes/` | market/store/service/as_of/packages/origin/destination | 有来源及有效期的quote或422/409阻断原因；缺档不报0 |
| POST `calculate/` | 完整country/schema/as_of/context及items/packages | 服务端解析规则和费用，返回结果、缺口及context；不信任前端合计 |
| POST `plans/save/` | 原始输入、expected_context_hash、幂等键；动作create/new_version | 同context重算并原子保存；不接受浏览器直接提供result；版本变化409 |
| GET `plans/`、`plans/{id}/versions/{id}/` | country过滤；组织/创建者权限 | 原始快照，不自动按当前费率重算；跨国访问不混币 |

以上不是承诺直接照搬现有ViewSet路径；实施可以共用原ViewSet/service，但必须清楚区分v1/v2、国家作用域和错误契约。

### calculate请求结构示意

```json
{
  "schema_version": 2,
  "country": "US",
  "currency": "USD",
  "store_id": "<store UUID or null>",
  "as_of": "2026-10-26T12:00:00-07:00",
  "seller_program": "local",
  "fulfillment_service": "seller_shipping",
  "rule_bundle_hash": "<verified hash>",
  "tax_profile_revision": 1,
  "shipping_quote_id": "<quote UUID>",
  "exchange_rate_set_id": "<rate set UUID>",
  "items": [{
    "client_item_id": "camera-1",
    "sku_id": "<SKU UUID or null for temporary trial>",
    "category_mapping_id": "<US verified mapping>",
    "quantity": 1,
    "unit_price": "100.00",
    "product_cost_cny": "140.00",
    "first_leg_cost_cny": "21.00",
    "affiliate_rate": "10.00"
  }],
  "packages": [{
    "client_package_id": "parcel-1",
    "items": [{"client_item_id": "camera-1", "quantity": 1}],
    "weight": {"value": "500", "unit": "g"},
    "dimensions": {"length": "20", "width": "15", "height": "10", "unit": "cm"},
    "battery_profile": "plug_in_no_battery"
  }]
}
```

示例是结构，不是生产数据／报价。临时SKU试算不自动创建主档；packages的数量合计必须恰好匹配items，不能漏件或重复装件。destination等必需物流信息由有效quote绑定，和当前包裹hash不一致即拒绝。

### calculate响应最低契约

country/currency、schema_version、calculation_status=`complete/partial`、context_hash、rule/quote/tax/rate版本、每SKU及订单汇总、费用计费粒度／基数／来源、原始及计费重量、included_components、warnings和missing_inputs。

`partial`仅用于明确允许的不完整预览，综合gross_profit/net_profit/break_even_roi为null；不能保存为正式方案。确定无适用服务、错币种或类目错国属于校验错误，不用partial掩盖。draft可单独保存输入，标签为“草稿，未完成计算”。

统一错误：401会话失效；403能力不足；404跨组织/不存在；409 revision/context/idempotency冲突；400结构非法；422 rule_not_verified/category_market_mismatch/shipping_not_supported/shipping_quote_missing/package_mismatch/tax_profile_incomplete；503报价或汇率来源不可用。前端根据code恢复，不匹配原始异常字符串。

## 4. 权限边界

保留profit_rules、profit_record_view/edit、exchange_manual及店铺/仓库权限的既有边界；国家切换不增加角色权限。无profit_rules的商品编辑者仍可维护被授权的店铺售价及查看既有允许的摘要，不能读取完整税务资料／公共规则编辑。官方规则发布、税务配置维护默认主账号；“看不到规则目录”与“无权保存业务数据”分别返回，不混为登录错误。

保存仍使用服务器权威context。具备手工汇率权限的用户通过受控接口生成manual快照，不能在calculate或save body里直接篡改换算值绕过权限。所有缓存键含organization/country/service/rule版本，不用全站单一config缓存。

## 5. 迁移与回滚计划

1. **盘点／备份**：确认实际生产SHA、迁移图、账号状态数量、店铺market原文、MY售价/方案/汇率数量；生成备份及抽样hash。只输出数量与安全摘要。
2. **扩展字段**：先加可兼容字段／表与索引，不删旧字段；旧账号employment=employed，auth_version=0，旧停用不自动离职。
3. **确定性回填**：旧MY售价复制为amount与MYR，旧MY计算配置加MY作用域，旧单默认策略改为MY默认。无法确定店铺国家或存在冲突的行列入人工清单，不猜US/MX；不能给所有空market店铺无条件认定MY。
4. **分国唯一约束**：校验无重复后切换工作配置／策略约束，建立国家币种校验。回填与约束各有迁移测试和数量／金额校验，分批可恢复。
5. **双读兼容**：旧MY客户端继续读取sale_price_myr；新客户端读通用金额。旧字段仅允许MY语义写入；US/MX拒绝旧字段写入，不把USD填进MYR。双写在同事务内完成。
6. **逐市场开放**：先P1账号，再MY v2对等，再US已核验服务，再MX已核验服务；每项有开关及回归条件。
7. **回滚**：关闭US/MX新增写入，保留已有新国数据、不可变快照和离职安全状态。回退兼容v1-MY代码前先验证它仍执行已离职账号的禁用与token代际保护，不能为了回滚重新放行旧token。

新增US/MX数据后，不允许直接执行会丢country／currency的新字段逆迁移，或把MY旧唯一约束强加给三国同名策略。逻辑回滚优先于删表。不得用整库恢复覆盖发布后新增订单、库存、人员操作；需要真正恢复数据时另行给出影响范围并确认。

本轮文档分支没有任何实际数据库变更。实施阶段必须交付真实迁移文件、可执行预检、回填报告、迁移前后对账和经验证的回滚步骤，不能只引用本计划当作已经做过。
