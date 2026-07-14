# 前端团队模式迁移方案

目标是在不破坏 GitHub Pages 本机模式的前提下，把当前 `localStorage` 前端逐步连接到自建 API。

> 当前进度：后端数据模型、权限与库存动作端点已完成；公开网页仍运行本机模式。阶段 A–D 是后续接入清单，不代表当前网页已经连接团队数据库。

## 1. 显式运行模式

前端只接受两种明确模式：

```js
window.DONGBO_CONFIG = {
  mode: "local",       // local | team
  apiBase: "/api",
  allowLocalFallback: false
};
```

- GitHub Pages 默认 `local`，保持当前行为。
- Docker 自建版注入 `team` 和同源 `/api/v1`。
- 团队模式连接失败时不得悄悄写回本机数据，否则会形成两套互相矛盾的库存。
- 页面顶部必须持续显示“本机模式”“团队模式”或“离线只读”。

## 2. 登录与会话

当前后端提供 JWT 访问令牌与刷新令牌：

- `POST /api/auth/token/`
- `POST /api/auth/token/refresh/`
- `GET /api/auth/me/`
- `GET /api/organizations/`

团队前端应把访问令牌放在内存中；HttpOnly 刷新 Cookie 与登出端点尚未实现，接入前不能按已完成功能宣传。当前 `auth/me` 返回用户、组织与角色，组织列表也可通过已认证 API 获取。

## 3. 前端数据访问层

把当前直接操作全局 `state` 的逻辑逐步收口到仓储接口：

```text
ProductRepository
PurchaseRepository
InventoryRepository
OrderRepository
MonitoringRepository
```

每个接口提供 `LocalRepository` 和 `ApiRepository` 两种实现。渲染层只调用统一接口，避免在业务函数中到处判断运行模式。

第一批需要改造的入口：

1. 商品新增、编辑、停用和图片上传。
2. 采购单创建、确认、收货和取消余量。
3. 库存调整与流水查询。
4. 订单创建、锁定、状态推进、出库和退货。
5. 竞品快照新增与删除。

## 4. 动作端点契约

普通档案可使用 CRUD；库存相关操作必须调用动作端点：

```text
POST /api/purchase-orders/{id}/submit/
POST /api/purchase-orders/{id}/cancel/
POST /api/receipts/
POST /api/stock-balances/adjust/
POST /api/orders/{id}/confirm/
POST /api/orders/{id}/allocate/
POST /api/orders/{id}/start-picking/
POST /api/orders/{id}/verify/
POST /api/orders/{id}/ship/
POST /api/orders/{id}/cancel/
POST /api/returns/{id}/receive/
POST /api/returns/{id}/reject/
```

当前动作把 `idempotency_key` 放在 JSON 请求体中。成功后前端重新读取单据、余额和流水，不自行猜测过账结果。

## 5. 图片策略

- 本机模式继续允许压缩后的 Data URL。
- 团队模式当前只接受可共享的外部 HTTPS 图片 URL。
- 团队模式禁止把 Data URL 直接保存到数据库。
- 预签名上传、MinIO/S3 与文件上传端点属于后续阶段。

## 6. 旧数据导入

以下是尚未实现的“完整 JSON 导入”目标流程，不要只依赖现有商品 CSV：

1. 前端读取并校验本机版本。
2. 向未来的 `/api/migrations/local-imports/validate/` 上传数据，返回商品、库存、采购、订单和快照摘要。
3. 用户选择库存权威设备并确认差异。
4. 使用同一个导入幂等键提交未来的 `/commit/` 端点。
5. 服务端事务落库并生成期初库存流水、迁移采购单和审计报告。
6. 前端保存导入报告编号，不自动删除旧本机数据。

## 7. 冲突与离线规则

- 档案更新携带 `updated_at` 或版本号，冲突返回 HTTP 409。
- 采购收货、库存调整、锁定、出库和退货不做离线写入队列。
- 网络中断时团队模式切换为只读，并保留尚未提交的表单草稿。
- 恢复连接后重新读取服务器状态，不直接重放未知结果的过账请求；先用幂等键查询执行结果。

## 8. 分阶段验收

### 阶段 A：只读连接

- 登录、组织和权限生效。
- 商品、库存、采购、订单和竞品列表来自 API。
- GitHub Pages 本机模式无变化。

### 阶段 B：档案写入

- 商品 CRUD、图片上传和竞品快照接入 API。
- 版本冲突有明确提示。

### 阶段 C：库存过账

- 收货、调整、锁定、出库和退货全部由服务端事务处理。
- 重复点击和网络重试不产生重复流水。

### 阶段 D：迁移与切换

- 完整 JSON 导入和对账报告通过。
- 多账号、多设备看到相同数据。
- 本机模式和团队模式不会在同一页面混写。
