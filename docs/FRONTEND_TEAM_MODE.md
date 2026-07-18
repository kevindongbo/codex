# 前端本机与团队模式

东铂跨境前端使用同一套页面支持两种明确的数据模式。公开静态站点保持本机演示；Docker/Caddy 自建版自动启用团队 PostgreSQL 数据库。两种模式不会在同一个页面混写业务数据。GitHub Pages 能访问并不代表联网团队版已经部署；正式团队版必须另有实际运行的 API、PostgreSQL、域名和 HTTPS。

## 1. 运行配置

默认 `runtime-config.js`：

```js
window.DONGBO_CONFIG = {
  mode: "local",       // local | team
  apiBase: "/api",
  allowLocalFallback: false
};
```

- GitHub Pages 和公开静态站点使用 `local`，业务数据保存到当前浏览器 `localStorage`，不会上传到 GitHub 或任何团队数据库。
- Docker 的 Caddy 在响应 `/runtime-config.js` 时注入 `team` 和同源 `/api`。
- 团队模式启动时先使用空状态，不读取本机业务键；连接失败时保持已同步数据只读，不降级到本机写入。
- 页面顶部和侧栏持续显示本机、同步中、团队已同步、待登录或离线只读状态。

## 2. 登录、组织与仓库

团队模式已经接入：

- `POST /api/auth/token/`
- `POST /api/auth/token/refresh/`
- `GET /api/auth/me/`
- `POST /api/organizations/`
- `GET /api/warehouses/`
- `POST /api/warehouses/`
- `PATCH /api/warehouses/{id}/`

访问令牌只保存在内存，刷新令牌临时保存在 `sessionStorage`；刷新请求采用单飞处理。组织作用域请求统一携带 `X-Organization-ID`。首次部署先用 `createsuperuser` 建立账号，账号登录后可在前端创建第一个组织，服务端同时生成 `DEFAULT` 默认仓。

仓库数量没有前端写死上限。仓库管理可创建或编辑海外仓、货代仓、学校仓、国内仓及其他仓库，并维护国家、时区、地址、联系人、允许收货、允许出库和启停状态。主仓配页面只在当前选中仓库内显示采购、库存、订单和补货建议；调拨页面显示与当前仓有关的来源/目标记录。停用仓库不会从历史单据中消失。

尚未实现自助邀请成员、密码重置、刷新令牌 HttpOnly Cookie 和服务端登出撤销；正式扩大团队前应补齐这些账号治理功能。

## 3. 数据访问与展示映射

`team.js` 中的 `TeamGateway` 统一处理认证、分页、组织/仓库切换、API 错误、幂等键和后端到现有界面的数据适配。所有 DRF 分页都会继续读取 `next`，不只统计第一页。

后端模型为：

```text
Product -> 多个 SKU
Warehouse × SKU -> StockBalance
Warehouse × SKU -> ReplenishmentPolicy
Source Warehouse -> StockTransfer -> Destination Warehouse
```

团队适配层为每个 SKU 生成独立的商品行，同时保留真实 `apiProductId`、`skuId` 和当前 `warehouseId`，不会静默只取第一个 SKU。本店商品可关联一个竞品监控档案，商品名称、链接、图片和启停状态在保存时同步到该档案。

本机 v6 状态新增 `warehouses`、`stockTransfers`、`replenishmentPolicies`、`replenishmentRecommendations` 和 `ui.warehouseId`。读取 v5 时会通过规范化逻辑补充 v6 默认字段并保留原有业务数据；不会因为版本升级清空商品、库存或历史记录。

## 4. 已接入的业务动作

普通档案使用 CRUD；库存和履约必须走服务端事务动作：

```text
POST /api/purchase-orders/{id}/submit/
POST /api/purchase-orders/{id}/cancel/
POST /api/receipts/
POST /api/stock-balances/adjust/
POST /api/stock-transfers/{id}/dispatch/
POST /api/stock-transfers/{id}/receive/
POST /api/stock-transfers/{id}/cancel/
GET  /api/replenishment/recommendations/?warehouse={warehouse_uuid}
POST /api/orders/{id}/confirm-and-ship/
POST /api/orders/{id}/confirm/
POST /api/orders/{id}/allocate/
POST /api/orders/{id}/start-picking/
POST /api/orders/{id}/verify/
POST /api/orders/{id}/ship/
POST /api/orders/{id}/cancel/
POST /api/returns/receive-from-order/
POST /api/competitor-snapshots/
POST /api/competitor-snapshots/quick-sales/
```

普通订单入口直接调用 `confirm-and-ship`，用户只确认一次。服务端在单个事务中完成确认、锁库、拣货/复核状态推进和出库；库存不足时整单失败。旧的确认、锁库、拣货、复核、出库按钮与接口不再作为普通路径，但分步端点仍保留给高级流程兼容。

调拨创建后可立即发出；发出扣来源仓，目标仓确认收货后才增加目标仓在库。前端在动作成功后重新读取单据、余额和流水，不自行推算团队模式最终结果。收货、调整、调拨发出/收货、一键出库、退货和本机迁移会保留幂等键；网络结果未知或 5xx 时，同一操作重试继续使用原键，避免重复过账。

## 5. 补货建议界面

补货页按当前仓库请求推荐接口，并展示：

- 近 7/15/30 天实际出库日速度及 50%/30%/20% 加权结果；
- 历史采购完整收货 P80、人工回退来源和高/中/低信心度；
- 可用库存、采购/调拨在途、库存位置、可用/预计覆盖天数；
- 预计缺货日、最晚下单日、补货点、建议采购量和红/黄/绿提醒；
- 样本不足、异常样本排除、下单时间近似、MOQ/整箱向上取整等解释原因。

用户可以按当前仓库和 SKU 设置人工采购周期、检查周期、目标覆盖天数、MOQ、整箱数和安全库存。建议采购按钮只帮助预填采购单，不会未经确认自动提交或改变库存。

## 6. 竞品快速销量

竞品没有历史时，快照表单要求先建立完整基线。已有历史时，常规入口只要求修改累计销量和采集时间，团队模式调用 `quick-sales`；价格、评分、评论数、上下架状态和原始字段由服务端继承最近快照。自动继承表示“沿用上次已知值”，不代表网站已经重新抓取这些字段。

## 7. 离线、权限与冲突

- `viewer` 及无写权限状态禁用业务写按钮。
- 网络中断时保留最后一次成功同步的页面数据，只读显示，不建立离线过账队列。
- 401 会尝试刷新一次；刷新失败清除团队会话并要求重新登录。
- 403、409 和字段校验错误直接显示服务端消息。
- 当前档案 CRUD 尚未实现真正的乐观锁，最后写入可能覆盖先前编辑；多人高频维护商品主档前应增加版本号或 `If-Match`。

## 8. 图片策略

- 本机模式允许从电脑选择图片，压缩后以 Data URL 保存到当前浏览器。
- 团队模式只接受所有成员可访问的 HTTPS 图片 URL，禁止保存 Data URL。
- 图片上传端点、对象存储和预签名上传尚未实现。

## 9. 完整 JSON 迁移

本机页面可下载第 6 版完整 JSON；页面仍可读取并保留第 5 版数据。团队迁移接口接受 v5 与 v6：

```text
POST /api/local-imports/validate/
POST /api/local-imports/commit/
GET  /api/local-imports/{id}/
```

迁移要求目标组织尚无业务数据，并先执行预检。提交后服务端在单个事务中导入：

- 本店商品、SKU、成本、安全库存和供应商；
- 可共享的 HTTPS 商品图片；
- 直接/间接竞品和公开数据快照；
- 通过不可变库存流水建立的期初在库；
- 本机 ID 到服务端 UUID 的映射、警告和审计报告。

v6 备份虽然包含多仓、调拨和补货参数，但当前服务端安全导入仍将期初库存写入用户选择的一个目标仓，不导入本机仓库结构、调拨或补货参数。为避免把旧状态误认为可继续操作的正式单据，当前版本也不导入已闭环的历史采购、销售订单、退货和旧流水；它们仍保留在原始 JSON 备份中。若备份中还有锁定库存、在途/部分收货采购、未出库订单或未完成退货，预检会直接阻止切换。非 HTTPS 图片和无法关联的记录会显示警告。导入不会自动删除或覆盖原浏览器数据。

## 10. 部署边界与仍需完善

代码仓库中的 Docker Compose、Caddy 和运行时配置可以组成联网团队版，但本项目文档不声称某个公开域名已经连接正式 PostgreSQL。GitHub Pages 与公开静态演示仍是 `local`。正式上线至少需要在目标服务器完成：环境变量与强密钥、数据库迁移、超级管理员、域名 DNS、HTTPS、备份/恢复演练、权限核对和两个账号的协作验收。

- 成员邀请、密码重置和更安全的刷新令牌策略。
- 商品主档聚合事务保存与乐观锁。
- 图片上传和对象存储。
- 历史单据的只读归档导入与更完整的迁移对账。
- 稳定业务错误码、列表端筛选和大数据量报表接口。
- 在真实服务器、域名、HTTPS 和 PostgreSQL 上完成恢复演练与多人验收。
