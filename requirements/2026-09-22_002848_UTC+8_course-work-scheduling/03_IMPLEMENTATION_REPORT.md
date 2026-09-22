# 实现与验证报告

记录日期：2026-09-22（Asia/Shanghai）。本报告补充完整需求，不替代、不删减 `01_REQUIREMENTS.md`。

## 分支与范围

- 需求分支：`codex/requirements-course-scheduling-20260922`，需求提交 `4f9a43e3fe5a9f3f3b99c09cee31450c26e99339`，已推送并核对远端。
- 实现分支：`codex/implement-course-scheduling-20260922`，独立 worktree，在需求提交之上实现。
- 没有修改或合并 main；没有执行生产部署、生产迁移或付费模型识别。
- 上传时间及原始需求核对见 README 与 02_IMPLEMENTATION。实现提交 SHA 以 Git 历史和最终推送回执为准。

## 实现位置

| 需求 | 实现与证据 | 状态 |
|---|---|---|
| 原始凭证与私密读取 | scheduling_models.py / scheduling_views.py：图片格式验证、像素限制、hash、私有文件保存；原图认证读取；本人和超级管理员限定 | 已实现；生产存储/Nginx验收待执行 |
| 图片识别与本人校对 | timetable_recognition.py、run_timetable_worker：视觉请求、DB租约、心跳、3次暂时故障重试、并发/小时限制；84格必须确认 | 已实现；真实视觉供应商识别质量未验证 |
| 全部无课成员自动排班 | scheduling_services.py：课程/休息/工作区分；未知不排班；12节参考时间原样保留 | 已实现并通过接口测试 |
| 至少20周、单周替换与周末选择 | 20—52周学期、独立周版本、周六默认、未来格重算、每周版本冲突校验 | 已实现；20周及单周替换自动测试通过 |
| 本人请假/外出直接生效 | adjustments/revoke：原因2—500字、仅本人、已开始时段受限；无审批流 | 已实现并通过测试 |
| 超级管理员修改与可选标注 | 超级管理员可强制覆盖课程/未知冲突，显式force；可不填写原因/隐藏标注，后台审计保留 | API与调整页面已实现；历史课表修正需通过API显式historical_correction，尚无独立历史修正页面 |
| 所有人查看工作安排 | board裁剪私密数据；仅状态、成员、计数；当前周/其他周、移动端单日、100人折叠 | 已实现；独立组件浏览器测试通过 |
| 两个左侧入口 | index.html、app.js、team.js、scheduling.js/css；原始凭证、工作安排；默认关闭开关 | 已实现；完整生产登录壳端到端未验收 |

## 精确接口差异与安全规则

- 实际采用手写白名单校验和序列化，集中在 scheduling_services/views，不额外建立空 serializers 文件。
- `POST evidence/` 返回 `{results:[...]}`，前端提取首项；服务端支持1—10张，前端逐张上传，方便每张独立草稿。
- `POST imports/` 接受 `selected_weeks` 或需求表中的 `week_indices`。
- `GET jobs/{id}/` 与入队返回 `id`、`status`、`warnings`，前端按 id 轮询。
- 模型配置属于学期：`PATCH terms/{id}/ {recognition_provider_id}`。当前管理页面把所选模型应用到全部学期，API支持逐学期设置。
- `PATCH participants/` 用 `target_user`；归档草稿必须提交 revision；history 返回 adjustments 与 versions。
- 所有业务修改使用 Idempotency-Key 和组织级事务锁；识别结果落库使用相同锁顺序，避免覆盖人工编辑。
- 普通 admin/manager 角色没有超级管理员特权。停用账号不能调用接口，停用参与人不进入未来工作表，历史记录保留。
- 通用审计只写动作及对象ID，不写课程和请假原因。课表私有原因/版本只在本人或超级管理员接口返回。
- 新模块没有调用采购、库存、补货或利润写入服务。

## 已运行验证

1. SQLite后端完整回归：196项，195通过、1项PostgreSQL专属并发测试跳过。测试使用临时生成的加密配置，不读取生产配置。修正了旧采购迁移测试的tearDown，使其恢复当前迁移叶子而非固定0037，避免污染后续测试。
2. PostgreSQL 16.15：21项排班/识别测试通过，包括两线程同时确认重叠周，一次200、一次409，未产生部分写入。
3. PostgreSQL隔离空数据库：全量正向迁移成功；0038逆迁移至0037成功；再次正向0038成功。此逆迁移仅针对无业务数据的测试库。
4. `makemigrations --check --dry-run`：No changes detected。
5. 63项前端/ERP/适配器测试通过。全量65项中旧部署脚本静态检查通过，Bash执行检查因本机没有 bash（ENOENT）未执行成功；没有删除或跳过其断言来伪造全绿。
6. 现有补货浏览器测试、利润工作流浏览器测试通过。
7. 新浏览器测试验证上传→校对84格→确认→请假→历史，1366/1440/1920/390/430宽度无横向溢出；100人名单和折叠；使用真实浏览器、模拟接口，不称为真实Django端到端测试。
8. 独立PostgreSQL容量测试：100人×20周×84格=168000行，10次当前周API请求；保守P95（取10次最大值）0.237秒。合成数据及本机指标不能等同生产网络/首屏指标。
9. 构建实际包含 scheduling.js/css；修改过的 app.js/team.js 已更新缓存版本。
10. 扩大为PostgreSQL全套196项后，发现8个失败、11个错误，集中在原有订单/退货服务的可空关联行锁查询。不是全系统绿灯。基线提交 `6d8add66a03a7f38c4d8db4437f85ac21d92573a` 的未修改原工作区独立复测 `InventoryServiceTests.test_cancel_blocks_active_reservation_above_unshipped_quantity`，同样在 services.py:1595 报 `FOR UPDATE cannot be applied to the nullable side of an outer join`。此次没有改动该业务服务文件；应另行审查锁范围及并发保护后修复，不把19项既有失败掩盖为通过。

## 仍须完成的上线验收（不标记为已完成）

- 获授权的真实课表图调用实际视觉供应商，检查合并课程、模糊、裁切、缺周末及识别费用；目前只使用无付费mock transport测试。
- 生产登录页面→真实API→数据库→worker→原图读取完整端到端验收；现有验证为API测试与浏览器模拟接口测试组合。
- 生产私有目录权限、Nginx拒绝直出、数据库迁移权限、备份恢复和worker systemd运行。
- Windows本机缺少Bash的旧部署脚本运行测试，应在Linux CI或部署预演环境补跑。
- 旧订单服务的PostgreSQL行锁兼容性问题已在基线复现；AC14全系统PostgreSQL回归尚未通过，不建议直接生产发布此分支。
- 管理员历史课表修正的专用UI、学期时间模板可视化编辑尚未提供；当前固定参考模板及对应API能力保留。
- 生产网络下首屏3秒目标未测；不是把API基准当首屏验收。

上线前不能仅依据健康接口或上述单元测试认定全部AC完成。功能默认关闭，适合先在隔离验收环境启用。
