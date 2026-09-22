# 排班模块迁移、运行与回滚

此文件是操作说明，当前任务没有执行生产部署。不要沿用旧的仅迁移到0037的ERP发布脚本来宣称排班已上线。

## 本次可执行发布脚本

使用仓库 `deploy/course-scheduling-release.sh`，先从**已核验的完整提交SHA**提取到 `/tmp`，运行 `bash -n`，再用独立Bash进程执行，并把该SHA作为唯一参数。最终交付消息提供精确SHA和完整复制命令。不要直接执行checkout内的脚本，否则切换版本可能改变正在执行的脚本。

脚本适用于当前已知架构：`/opt/dongbo/app`、`/opt/dongbo/venv/bin/python`、`dongbo-erp.service`、本机5432端口数据库 `dongbo_erp`、域名 `dongbokeji.com`；现场不匹配会停止，不自行改成其他数据库、服务或路径。要求当前代码是目标祖先，已应用旧迁移，无已跟踪改动；不改main、不强制重置、不修改表所有者、不fake迁移。

执行有短暂服务暂停，请在维护窗口运行。脚本在停止Web和已有worker后备份数据库及现有原图，再更新代码，执行0038，启动服务并验证源站资源。备份放在 `/opt/dongbo/backups/course-scheduling-*`，备份日志保持私有。

- 私有原图：`/var/lib/dongbo-timetables`，由现有非root Web运行账号持有，目录0700；不会放入静态或MEDIA目录。
- 功能配置：`/etc/dongbo/scheduling.env`，仅写功能开关和私有目录，不含模型密钥，不覆盖生产 `.env`。
- Web附加配置：`/etc/systemd/system/dongbo-erp.service.d/50-course-scheduling.conf`，加载上述配置并允许受限服务写私有目录。
- 独立worker：`dongbo-timetable-worker.service`，与Web使用同一账号和数据库配置，失败自动重启。
- 依赖：仅在缺失/不兼容时安装 `Pillow>=11,<13`，不升级现有Django等依赖。失败回滚保留这个新增兼容依赖。
- 失败后自动恢复上一代码及上述配置的备份，并验证健康及资源hash；**保留新表、原图、期间业务数据**。回滚不恢复整库，不反向执行0038。

若提示历史迁移、所有权、目录或SHA不符，把错误日志发回核对；不要重复旧SQL、递归chmod、手工fake或移除脚本检查。

## 部署后首次使用

1. 超级管理员登录，进入“团队排班 → 学期与识别设置”，配置真实第一周周一日期和20—52周，按需在首次确认前调整时间模板。
2. 选择已有的支持图片输入的视觉模型。模型尚未配置时可上传、保存原图并手工校对；此时不能说自动识别已验证。
3. 成员进入“原始凭证”，上传、选择周次及周末工作日，检查七天84格后确认。未确认不会被当成有空。
4. “工作安排”默认显示实际当前周；验证请假、管理员标注、其他成员不可读取原图/私有原因。
5. 刷新浏览器缓存并核对新JS/CSS。观察 `systemctl is-active dongbo-erp.service dongbo-timetable-worker.service`；服务active不替代真实识别验收。

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
