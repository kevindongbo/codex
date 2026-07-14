# 东铂跨境 ERP 后端

这是一个可自建部署的 Django/DRF 模块化单体底座。库存数量只能通过事务服务变化；`StockLedger` 与 `AuditLog` 对普通 ORM 保存/删除保持不可变。

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
```

容器监听 `8000`，健康检查为 `GET /api/health/`；静态文件与媒体目录分别是 `/app/staticfiles`、`/app/media`。当前 `ProductImage` 只保存外部图片 URL，没有文件上传端点或对象存储依赖；媒体目录是后续本地文件字段的预留位置。

## API 约定

1. `POST /api/auth/token/` 获取 JWT，`POST /api/auth/token/refresh/` 刷新，`GET /api/auth/me/` 获取当前用户、组织与角色。
2. 除健康检查和登录外，业务请求需要认证。
3. 业务请求通过 `X-Organization-ID` 选择组织，服务端校验当前用户的有效成员关系。
4. 写操作按角色授权：`admin`、`manager`、`buyer`、`warehouse`、`viewer`。
5. 收货、库存调整、锁库、出库必须携带业务幂等键，并使用专用端点：
   - `POST /api/products/{id}/activate/`
   - `POST /api/purchase-orders/{id}/submit/`
   - `POST /api/purchase-orders/{id}/cancel/`
   - `POST /api/receipts/`
   - `POST /api/stock-balances/adjust/`
   - `POST /api/orders/{id}/confirm/`
   - `POST /api/orders/{id}/allocate/`
   - `POST /api/orders/{id}/start-picking/`
   - `POST /api/orders/{id}/verify/`
   - `POST /api/orders/{id}/ship/`
   - `POST /api/orders/{id}/cancel/`
   - `POST /api/returns/{id}/receive/`
   - `POST /api/returns/{id}/reject/`

所有路由都保留末尾斜杠。健康检查是 `GET /api/health/`；常用资源集合包括 `GET/POST /api/products/`、`/api/skus/`、`/api/purchase-orders/` 和 `/api/orders/`。

## 验证

```bash
python manage.py makemigrations --check
python manage.py check
python manage.py test
```
