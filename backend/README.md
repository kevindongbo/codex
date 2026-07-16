# 东铂跨境 ERP 后端

这是一个可自建部署的 Django/DRF 模块化单体。团队模式使用 PostgreSQL 作为唯一事实来源；库存数量只能通过事务服务变化，`StockLedger` 与 `AuditLog` 对普通 ORM 保存/删除保持不可变。

## v2 服务端能力

- `Warehouse` 支持海外仓、货代仓、学校仓、国内仓和其他仓库类型；组织内仓库数量没有业务层硬编码上限。仓库可维护国家、IANA 时区、地址、联系人、收货/出库能力和启停状态。
- `StockBalance`、采购、订单、退货与库存流水全部按仓库隔离。`StockTransfer` 发出、收货和在途撤回通过行锁与事务过账；发出/收货要求外部幂等键，撤回流水使用调拨明细派生的确定性键。
- `ReplenishmentPolicy` 按“仓库 × SKU”保存人工采购周期、检查周期、目标覆盖天数、MOQ、整箱数和安全库存覆盖；推荐接口输出可解释的计算过程与信心度。
- `confirm-and-ship` 将确认、整单锁库、拣货、复核和出库包装为一个原子操作。库存不足、状态冲突或任一过账失败时，数据库事务整体回滚。
- `quick-sales` 要求竞品已有一条完整基线快照，之后只接收累计销量和可选采集时间，其余公开字段从最近快照继承。

## 本地运行

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=true
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

未设置 `DATABASE_URL` 时使用 SQLite，测试与本地开发无需 PostgreSQL。生产建议：

```text
DATABASE_URL=postgresql://erp:password@db:5432/erp
DJANGO_SECRET_KEY=<at-least-50-random-characters>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=erp.example.com,127.0.0.1
DJANGO_CORS_ALLOWED_ORIGINS=https://erp.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://erp.example.com
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
DJANGO_TIME_ZONE=Asia/Shanghai
DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE=26214400
```

容器监听 `8000`，健康检查为 `GET /api/health/`；静态文件与媒体目录分别是 `/app/staticfiles`、`/app/media`。商品图片可使用外部 HTTPS 地址，也可通过 `POST /api/uploads/product-images/` 上传 JPG、PNG 或 WebP（最大 8MB）；服务会将文件存入媒体目录，并返回可供团队成员访问的图片地址。

## API 约定

1. `POST /api/auth/token/` 获取 JWT，`POST /api/auth/token/refresh/` 刷新，`GET /api/auth/me/` 获取当前用户、组织与角色。
2. 除健康检查和登录外，业务请求需要认证。
3. 业务请求通过 `X-Organization-ID` 选择组织，服务端校验当前用户的有效成员关系。
4. 写操作按角色授权：`admin`、`manager`、`buyer`、`warehouse`、`viewer`。
5. 收货、库存调整、调拨发出/收货、一键出库和退货收货必须携带业务幂等键，并使用专用动作端点。重复提交同一键和同一业务内容返回原结果；同键不同内容会被拒绝。

所有路由都保留末尾斜杠。

### 认证与系统

```text
GET   /api/health/
POST  /api/auth/token/
POST  /api/auth/token/refresh/
GET   /api/auth/me/
```

### 资源集合

下列集合通过 DRF Router 提供与权限相符的列表、详情和 CRUD；只读集合只提供读取操作。

```text
/api/organizations/          /api/memberships/
/api/warehouses/             /api/products/
/api/product-images/         /api/skus/
/api/suppliers/              /api/purchase-orders/
/api/receipts/               /api/stock-balances/
/api/stock-ledger/           /api/stock-transfers/
/api/replenishment-policies/ /api/orders/
/api/shipments/              /api/returns/
/api/competitors/            /api/competitor-snapshots/
/api/audit-logs/             /api/local-imports/
```

`receipts`、`stock-ledger`、`shipments`、`audit-logs` 和 `local-imports` 的可写范围受各自 ViewSet 限制，不能把资源集合的存在理解为允许直接改写已过账记录。

### 业务动作

```text
POST /api/products/{id}/activate/
POST /api/products/{id}/deactivate/

POST /api/purchase-orders/{id}/submit/
POST /api/purchase-orders/{id}/cancel/
POST /api/receipts/
POST /api/stock-balances/adjust/

POST /api/stock-transfers/{id}/dispatch/
POST /api/stock-transfers/{id}/receive/
POST /api/stock-transfers/{id}/cancel/

GET  /api/replenishment/recommendations/?warehouse={warehouse_uuid}

POST /api/orders/{id}/confirm-and-ship/
POST /api/orders/{id}/confirm/            # 兼容分步流程
POST /api/orders/{id}/allocate/           # 兼容分步流程
POST /api/orders/{id}/start-picking/      # 兼容分步流程
POST /api/orders/{id}/verify/             # 兼容分步流程
POST /api/orders/{id}/ship/               # 兼容分步流程
POST /api/orders/{id}/cancel/

POST /api/returns/receive-from-order/
POST /api/returns/{id}/receive/
POST /api/returns/{id}/reject/

POST /api/competitor-snapshots/quick-sales/
POST /api/local-imports/validate/
POST /api/local-imports/commit/
```

`confirm-and-ship` 请求体为 `idempotency_key`，并可选传入出库单号 `number` 与物流单号 `tracking_number`。`quick-sales` 请求体为 `product`、`sold_count` 与可选 `captured_at`；若没有基线快照会返回校验错误。

## 补货计算与信心度

```text
加权日速度 = 7 天日均 × 0.50 + 14 天日均 × 0.30 + 30 天日均 × 0.20
库存位置 = 可用库存 + 已提交/部分收货采购在途 + 调拨在途
安全库存 = max(日速度 × 安全天数, 人工安全库存)
补货点 = 日速度 ×（采购周期 + 检查周期）+ 安全库存
目标库存位置 = 日速度 ×（采购周期 + max(目标覆盖天数, 检查周期)）+ 安全库存
建议量 = max(0, 目标库存位置 - 当前库存位置)，再按 MOQ 和整箱数向上取整
```

采购周期采用完整收货历史 P80：完整样本至少 8 个为高信心、3–7 个为中信心、1–2 个为低信心；没有完整样本时用首次收货 P80，没有任何历史时用人工默认周期，这两种均为低信心。出库速度覆盖至少 28 天且有至少 10 个活跃出库日为高信心；覆盖至少 13 天且有至少 3 个活跃出库日为中信心；否则为低信心。最终信心度取两项中较低者。

推荐接口还返回已排除异常周期、使用创建时间替代下单时间、历史样本不足等 `reasons`。提醒等级为 `red`（已触发补货）、`yellow`（接近补货点）和 `green`（暂时健康），它是决策辅助而不是自动采购指令。

## 本机备份版本

`POST /api/local-imports/validate/` 与 `commit/` 接受状态版本 v5 和 v6。v6 新增本机多仓、调拨和补货参数，但当前服务端安全导入范围仍是商品/SKU、可共享 HTTPS 图片、竞品/快照和指定目标仓的期初库存；不会导入多仓结构、调拨、补货参数或历史过账单据。导入前必须保留原始 JSON 并核对预检报告。

## 验证

```bash
python manage.py makemigrations --check
python manage.py check
python manage.py test
```
