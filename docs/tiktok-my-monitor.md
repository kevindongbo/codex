# 马来西亚 TikTok Shop 竞品监控

本功能只采集买家可见的公开商品数据：当前价格、累计销量、评分、评论数、公开库存状态、图片和部分 SKU 公开信息。它不会登录竞争对手后台，也不能获得竞争对手的逐笔订单。

第一条快照是基准值；从第二条开始，系统用“本次累计销量 - 上次累计销量”计算区间销量。累计销量下降不会被当作负销量，而会在快照中标记异常，等待人工核对。

## 提供商顺序

1. TikHub：主通道，使用商品 ID 和 `region=MY` 获取马来区数据。
2. Apify：TikHub 无数据或暂时失败时的备用通道，固定使用马来西亚住宅出口，并限制单个任务最高费用。
3. 手动快照：两个自动通道都不可用时，网页仍保留原有的“手动更新”。

## 服务器配置

把密钥写入服务器 `/opt/dongbo/app/.env`，不要写入 Git，也不要放在浏览器代码中：

```dotenv
TIKTOK_MONITOR_DEFAULT_MARKET=MY
TIKTOK_MONITOR_INTERVAL_MINUTES=60
TIKHUB_API_TOKEN=你的_TikHub_Token

# 可选的备用通道
APIFY_API_TOKEN=你的_Apify_Token
APIFY_TIKTOK_ACTOR_ID=bovi/tiktok-shop-scraper
APIFY_TIKTOK_MAX_CHARGE_USD=0.25
```

只配置 TikHub 也可以运行；配置 Apify 后才会自动切换备用通道。修改 `.env` 后，不需要把密钥发送到前端。

## 手动预检

```bash
cd /opt/dongbo/app/backend
set -a
. ../.env
set +a
/opt/dongbo/venv/bin/python manage.py monitor_tiktok_products --market MY --dry-run
/opt/dongbo/venv/bin/python manage.py monitor_tiktok_products --market MY --limit 1 --force --strict
```

`--dry-run` 只列出目标，不调用收费接口。第二条命令只采集一个竞品，适合首次验证密钥、马来区商品链接和返回字段。

## 启用定时采集

```bash
cp /opt/dongbo/app/deploy/dongbo-tiktok-monitor.service /etc/systemd/system/
cp /opt/dongbo/app/deploy/dongbo-tiktok-monitor.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dongbo-tiktok-monitor.timer
systemctl start dongbo-tiktok-monitor.service
systemctl status dongbo-tiktok-monitor.timer --no-pager
journalctl -u dongbo-tiktok-monitor.service -n 100 --no-pager
```

定时器每 15 分钟检查一次；命令会按照 `TIKTOK_MONITOR_INTERVAL_MINUTES` 跳过尚未到期的商品，默认每个商品每 60 分钟实际采集一次。这样既能在服务重启后自动补跑，也能控制接口费用。

## 网页使用

新增或编辑竞品时选择“马来西亚 MY”，并填写带商品 ID 的完整 TikTok Shop 商品链接。保存后在“竞品监控”列表点击“立即采集”。短链接如果没有公开商品 ID，会提示改用完整链接。

自动采集失败不会覆盖旧快照。页面仍可使用“手动更新”，服务器日志会记录失败的提供商和原因，但不会记录 API Token。
