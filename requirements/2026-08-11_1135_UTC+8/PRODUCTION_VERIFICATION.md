# 生产环境验证要求（修复完成后再执行）

本文件只定义验证要求，不代表允许 Codex 直接连接或操作阿里云生产。

## A. 修复前只读确认

在生产服务器项目目录执行：

```bash
git branch --show-current
git rev-parse HEAD
git status --short
python backend/manage.py showmigrations erp | tail -30
```

记录：生产分支、40位 SHA、0028/0029 是否已执行。

如果需要定位当前 HTTP 500，只读取真实应用日志，重点搜索：

- 订单号 `SO-20260811-7499`
- `AI-BAG-JALUR-08`
- `AttributeError`
- `NoneType`
- `confirm-and-ship`
- `/api/orders/`

不要为了排错直接修改数据库。

## B. 第二轮修复上线前门槛

必须先拿到 Codex 新最终 SHA，并确认：

- PR #12 已更新；
- P0/P1 验收通过；
- 新 migration 文件确定；
- 完整自动化测试通过；
- 生产数据库已备份；
- 生产旧 SHA 已记录。

## C. 上线后必须验证

至少验证：

1. 未映射 SKU 订单不会 500，而是明确提示 SKU 未映射。
2. 无仓订单可以选择仓库。
3. 库存不足时显示具体 SKU 缺口且不产生部分预占。
4. 库存足够时选择仓库后 reserved 正确增加。
5. 库存列表能看到 已采购待发货 / 在途库存。
6. 采购提交只增加 pending，不增加 in-transit。
7. 采购确认发货把相应数量 pending -> in-transit。
8. 调拨创建预占，确认发货后来源扣库、目的形成在途。
9. 调拨部分收货可重复进行。
10. 智能补货统一销量不包含手动出库。

## D. 阿里云部署命令生成规则

最终部署命令必须基于“第二轮修复后的真实最终 SHA + 实际新增 migration + 当前生产真实服务名/目录”生成。

不得提前猜：

- 项目目录；
- PostgreSQL 数据库名/用户；
- systemd service 名；
- Nginx 配置路径；
- Python venv 路径。

最终部署脚本必须包含：代码/数据库备份、精确 SHA checkout、migration、前端 build、collectstatic（如生产使用）、真实服务重启、health check、日志检查、精确 SHA 验证和回滚方案。
