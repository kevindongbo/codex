# 排班模块迁移、运行与回滚

此文件是操作说明，当前任务没有执行生产部署。不要沿用旧的仅迁移到0037的ERP发布脚本来宣称排班已上线。

## 预检

1. 确认待发布为独立实现分支的已验收精确提交，工作区干净；不要切换、覆盖或推送main。
2. 备份数据库并验证备份可读；已有排班数据时同步备份私有原图目录，限制备份访问权限。
3. 查验实际Web服务账号、Python虚拟环境、数据库迁移角色和代码目录；不要猜测或打印生产.env。
4. 迁移角色需有创建新表、索引、外键权限；运行账号要能读取代码、写私有图片目录。不要递归chmod整个项目，不要更改密钥权限。
5. 使用更新的 backend/requirements.txt 安装Pillow；保持生产其他依赖版本锁定策略。图片仅JPG/PNG/WebP，10MB和2500万像素上限。

## 配置与运行（在已加载正确生产环境的虚拟环境执行）

- `SCHEDULING_ENABLED` 默认false。先保持关闭，完成迁移和私有存储准备后在验收环境设true。
- `SCHEDULING_PRIVATE_ROOT` 指向不在MEDIA_ROOT、不被Nginx/static映射的绝对目录。只授予Web与worker服务账号所需权限。不得将目录放入Git。
- 现有 `INTEGRATION_ENCRYPTION_KEY` 保持不变；API Key沿用系统加密模型配置，不在脚本、日志或Git保存。

```bash
python manage.py check
python manage.py showmigrations erp
python manage.py migrate --plan
python manage.py migrate erp 0038_course_work_scheduling --noinput
python manage.py showmigrations erp
node scripts/build-site.mjs
```

上述命令的工作目录：manage.py命令在backend；node命令在仓库根目录。先审阅migrate --plan，若包含与本功能无关的未应用旧迁移，停止并单独处理，不用--fake跳过。

Web与worker加载相同数据库、功能开关、私有目录与加密配置。独立worker命令：

```bash
python manage.py run_timetable_worker --poll-seconds 3
```

由实际服务管理器托管，设置Restart=on-failure、非root账号和受限环境文件；不要从交互终端后台裸跑当长期服务。启动后先用一张获授权测试图片核对OCR和人工确认流程，不把已有业务图片批量送往未经确认的供应商。

超级管理员在“学期与识别设置”创建周一起始、20—52周学期，选择支持图片输入的模型配置；成员上传并确认后才生成正式安排。模型未配置时原图与手工校对仍可使用。

## 验证

执行需求AC01—AC14，特别检查：他人不能读原图/私有原因；未提交者不是无课；课表重算保留请假；两人同时确认冲突返回409；周末默认周六；生产浏览器实际加载新的JS/CSS；旧采购库存流程不变。

## 回滚

1. 将SCHEDULING_ENABLED关闭并停止独立worker，重启/重载Web使开关生效。
2. 必要时按既有安全发布方式回到发布前已验证代码提交；保留所有排班表、原图与审计记录。
3. 不执行生产 `migrate erp 0037`，此操作会删除新表。该逆迁移只在本次无业务数据的本机测试数据库验证过。
4. 不恢复整库覆盖期间新增的采购、库存或排班数据。疑似数据问题必须专项处理。
