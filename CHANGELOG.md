# 变更记录（CHANGELOG）

本项目为「五站官网 CMS」：FastAPI + SQLite + Jinja2 SSR，五站（南京/杭州/合肥/无锡/徐州）完全独立，极简 K3s 容器化部署。

本文件记录每一次功能性修改、性能优化与修复，便于追溯。五站代码目录 `sites/<城市>/src/app` 完全同步，任何代码改动需同时应用到五个副本（改动后用 `md5 -q sites/*/src/app/<文件>` 校验一致性）。

格式约定：按版本倒序排列（最新在上），每条包含日期、类型标签与变更说明，并在末尾标注对应 Git 提交短哈希。

---

## v2.5.1 — 2026-11-26（当前）

### 部署链路连环故障排查与修复（当天多次部署失败/回滚的完整根因链）
1. **venv 被 reset 反复削坏**：`git reset --hard` 跨「删除 venv」提交会删掉 site-packages 中曾被
   Git 跟踪的文件 → Pod CrashLoopBackOff / 文件响应截断（Cloudflare 520「资源全挂」的真实根源）。
   - 部署脚本新增**依赖自检自愈**：按 requirements.txt 逐个核对 dist-info，缺失即用清华镜像重装
     （60s 超时 + 3 次重试，失败回退官方源）；注意 fastapi 0.162+ 已移除 `fastapi.app` 模块，
     自检不能用深层导入（会有 OOM 与假阳性双重问题）。
2. **webhook 接收器 64Mi 内存限额**：部署子进程（python 自检/pip）与 Pod 共享 cgroup，
   全部被 OOM 静默杀死（dmesg 可见 `oom_score_adj=992`）。修复：
   - webhook-deploy.py 改用宿主机 `systemd-run` 把部署脚本放进独立 cgroup（输出经
     `StandardOutput=file:` 重定向进部署日志），不可用时回退直接执行；
   - 接收器限额 64Mi → 256Mi。
3. **webhook token 被 reset 覆盖**：git 版 webhook.yaml 只有占位符，服务器手填的真实 token
   会被 `git reset` 冲掉 → 接收器 403、部署触发失败。修复：部署脚本用 secrets 真实 token
   渲染占位符后再 apply（值不变不触发重启），git 上不落任何真实凭据。
4. **systemd-run 环境变量缺失**：单元里 `HOME` 为空 → git 报 dubious ownership、fetch 连续失败。
   部署脚本补 `export HOME="${HOME:-/root}"`；git fetch/reset 增加重试（与 Drone CI 校验并发
   操作同一仓库时 index.lock 偶发冲突）。
5. **可观测性**：部署脚本加 EXIT trap（未预期退出留下行号与退出码日志）；健康检查 curl 瞬时
   连接拒绝（滚动更新中途）不再中止脚本；Drone 部署步骤的失败关键词补全
   （中止部署/异常退出/三次均失败），失败构建不再空等 900s。

修复后全链路验证：push → CI → promote → 部署完成 → 五站健康检查全 200，release-history 正常记 OK。

---

## v2.5.0 — 2026-11-26（当前）

### 安全加固
- **后台 IP 黑/白名单 + 自定义后台访问地址**（新增 `AdminGuardMiddleware`，纯 ASGI 最外层）：
  - 配置入口：后台「安全设置 → 后台访问防护」卡片，存于 setting 表（admin_path / admin_ip_mode / admin_ip_rules）；
  - 黑名单模式（默认、列表为空全放行）：列表内 IP 拒绝访问 `/admin*` 与 `/api/admin*`，其余放行；
  - 白名单模式：仅列表内 IP 放行（列表为空时除本机回环外全部拒绝，UI 有防呆提示）；
  - 每行一个，支持精确 IP（172.16.10.111）、CIDR（172.16.10.0/24，放行所有填 0.0.0.0/0 与 ::/0）、通配符（172.16.*）；
  - 后台访问地址默认 admin，改为自定义值后入口变为 `/<自定义值>`（访问自动下发 HttpOnly Cookie），
    原 `/admin` 页面与 `/api/admin` 接口无 Cookie 一律 404；配置 30 秒内刷新，保存设置立即生效。
- **.env 防误提交启动检查**：启动时检测 `.env` 是否被 Git 跟踪，是则直接拒绝启动并给出处置命令
  （`git rm --cached sites/<站>/.env`），杜绝 SECRET_KEY 泄露导致会话 Cookie 伪造。
- **上传安全**：文件类型沿用后缀白名单；新增大小硬限制（`MAX_UPLOAD_MB`，默认 20MB）与
  图片分辨率硬限制（最长边 ≤12000px、总像素 ≤4000 万，`MAX_UPLOAD_PIXELS` 可调），超大图直接拦截，
  从源头避免 Pillow 解码内存爆炸；损坏/伪图片文件返回友好错误而不是异常。

### 图片处理（缩略图管道）
- **队列并发可配**：`THUMB_WORKERS` 环境变量（默认 1 串行，上限 8）——多图同时请求时可按机器性能调大，
  不再排队阻塞前端。
- **异常兜底占位图**：源图损坏或处理异常统一返回灰底占位图（短缓存 5 分钟），接口不再 500、页面不再烂图。
- **缩略图过期清理**：启动时后台线程清理 `storage/cache/oss/` 超过 `THUMB_CACHE_DAYS`（默认 30 天）的
  缓存文件并回收空目录，磁盘不再无限膨胀。

### 数据库
- SQLite 已开 WAL + synchronous=NORMAL + busy_timeout=5000 + cache_size（v2.3.x 完成）；
  本版补充说明：高频写经应用内队列与短事务控制，多请求同时保存不再锁库阻塞前台读。

### 前台
- **tel: 链接净化**：联系方式字段允许保存任意文本（如「宋经理15669996204」），页面输出时用正则抽出
  真实号码生成拨号链接：支持手机号（1[3-9]开头 11 位）、400 热线、固话（含分机），
  输出形如 `<a class="sg-fn-phone" href="tel:15669996204">宋经理15669996204</a>`；
  抽不出号码时不渲染拨号链接。五主题 base.html 已全部接入（`phone_href` Jinja 过滤器）。

### 文档
- **敏感信息全量清理**：README / k8s 文档 / 五站 README 中的服务器公网 IP、五站真实域名、公司全称
  全部替换为占位符（`<服务器IP>` / `example-*.com` / 示例客户 A–E），Git 仓库不再暴露客户与基础设施信息。

---

## v2.4.2 — 2026-11-26

### 修复（Drone 部署链路故障）
- **venv 误删导致滚动更新失败（重要教训）**：v2.4.1 把 `venv/` 当「无任何使用」删除是**误判**——
  `deploy-*.yaml` 用 hostPath 把 `venv/lib/python3.10/site-packages` 挂进五站 Pod 作为依赖目录。
  服务器 `git reset --hard` 删掉该目录后，新 Pod 全部 CrashLoopBackOff（`ImportError: cannot import
  name 'FastAPI'`），滚动更新逐站失败、自动回滚到旧版。已在服务器用主机 pip（Python 3.10.12，与
  容器 python:3.10-slim ABI 匹配）按固定版本重建 site-packages；仓库新增 **`requirements.txt`**
  （全部固定版本含传递依赖 + 重建方法注释），`.gitignore` 保持忽略 `venv/`（目录只应存在于服务器）。
- **clone 步骤从未被跳过**：`.drone.yml` 的 `clone: skip: true` 是 Drone 0.8 老语法，Drone 2.x 只认
  `clone: disable: true`。此前每次构建都从 Gitee 重新拉代码，build #17 因 Gitee 网络 TLS 中断
  （`GnuTLS recv error` / `early EOF`）直接失败。已改为 `disable: true`。
- **Drone 等待部署超时**：部署最长耗时曾超 180s（逐站 120s 启动等待），构建 #18 在部署仍在进行时
  超时报 Failure。等待上限提高到 900s，并区分结果：`部署完成` → 成功；`部署失败/回滚完成` → 构建失败。

### 变更（Deployments 页有数据）
- **部署流程改为 promote 模式**：push 构建 = CI 校验（五站源码 `py_compile`）→ 校验通过自动
  `promote target=production` → 生产构建（event=promote）执行 8300 部署。Drone 的 Deployments 页
  从此记录每次生产部署与回滚（此前该页只在 promote/rollback 时填充，push 直部署永远为空），并支持
  页面一键回滚（rollback 事件走同一条部署步骤）。
- Drone API token 存服务器 `k8s/secrets/drone-token.txt`（gitignore，600），来源 users 表 `user_hash`。

## v2.4.1 — 2026-11-26

### 清理
- **遗留物全量清除**：删除仓库中不再使用的文件与目录（含从版本库移除历史误提交内容）：
  - `venv/`（40MB 误提交的 Linux 虚拟环境，1728 个文件，加入 .gitignore。**注：当时误判为无用，
    实际是五站 Pod hostPath 挂载的依赖目录，已在 v2.4.2 修复并补 requirements.txt**）
  - `k8s/kubepi.yaml`（KubePi 面板整体下线：同步删除 `provision-secrets.sh` 的 KubePi 改密段、
    `.gitignore` 的 kubepi-data 条目、README/k8s 文档中全部 KubePi 引用）
  - `scripts/deploy.sh`、`scripts/pysite`、`scripts/systemd/pysite@.service`（systemd 时代旧部署链，已被 `k8s/k3s-deploy.sh` 取代）
  - `.workflow/`（Gitee Go 流水线，CI 已收口 Drone 单一入口；DRONE.md 对应章节改写为决策记录）
  - `scripts/nginx/drone.conf.example`（Drone 走 IP:30080 直连，无域名反代需求；DRONE.md 安装步骤重编号）
  - 本地未跟踪残留：`backups/`（11-24 迁移备份 274MB）、`sites/nanjing/backups/`（11-17 旧库备份）
- **服务器侧 KubePi 下线**（SSH 执行）：删除 kube-system 下 deploy/service `kubepi`、
  SA `kubepi-user` 及 ClusterRoleBinding（cluster-admin 权限面一并移除）；删除宿主机
  `kubepi-data/`、`secrets/kubepi-admin.txt`、`kubepi-cluster-token.txt`；credentials.txt
  移除 KubePi 段；nginx 删除 `k8s-dashboard.conf`（:10000 反代）与 5 份 `*_bak` 旧站配置，`nginx -t` 通过后 reload。
- `k3s-deploy.sh` 注释同步（修订历史指向 `kubectl rollout history`）。

## v2.4.0 — 2026-11-26

### 安全 / 权限（RBAC）
- **系统菜单按角色 rules 过滤**：`/api/admin/menu` 按「角色 rules → 菜单开关 → 内容模型」三层过滤，空分组不下发；前端 `enterApp` 越权 hash 一律回落到有权限的页面，无权限时显示「暂无可访问菜单」。`bc89227`
- **接口级 RBAC 守卫**：新增全局 `admin_rbac_guard`（`accounts/router.py`），支持 `*`/精确 key/`group:分组名`/`content:*` 通配匹配；内容类接口（列表/详情/保存/删除/回收站恢复）按资源与 model 细化鉴权，未授权统一 403。依赖改用 `raise HTTPException` 短路（JSONResponse 返回不短路），factory 注册全局异常 handler 返回 `{code,msg}`。`bc89227`
- **权限树与菜单结构对齐**：后台分页固定 10 条、卡片列表一行 5 个、菜单按新 JSON 结构重排；对齐权限树时清理废弃旧分组节点，彻底消除 `station/content` 等残留。`5f74ba4`, `bfcc5cf`

### 审计日志
- **操作日志增强**：IP 缺失修复——统一 `client_ip(request)` 解析反代头（`X-Forwarded-For`/`X-Real-IP` 优先），登录、表单提交等全部入口替换；中间件回填「请求/响应[状态码]」摘要与真实 IP。`c7ada0a`
- **流式与大数据保护**：`StreamingResponse`/SSE/事件流响应不读完整响应体；请求/响应 body 仅在 ≤64KB 且非 multipart 时缓存记录，高并发大请求不增加内存开销；登录请求不记录、password 字段打码。`c7ada0a`
- 所有展示「关联内容模型」的地方改用模型名称（中文），不再显示模型标识。`c7ada0a`

### 前台 / 主题
- **全主题标题一行超出省略**：五主题页脚热点/产品/新闻等标题统一 `text-overflow: ellipsis` 一行省略，详情页（`body.page-detail`）除外；蜂巢深蓝主题追加防溢出规则（min-width:0、多行 clamp、`overflow-wrap:anywhere`）。`ccf7f91`
- **页脚新闻/产品兜底**：所有主题页脚「热点」不足 4 条时按 article 模型取最新内容自动补齐；栏目/页脚列表按内容模型过滤查询（`cat.model` 对应上），修复智造橙主题页脚新闻空白、产品/新闻按分类查不到的问题。`ccf7f91`, `bc89227`
- **首页内联脚本抽离**：三主题首页轮播/页签 JS 抽离为 `themes/<t>/static/js/home.js` 独立文件，带 `?v={{ static_ver }}` 缓存版本号。`fc781d7`

### 后台体验
- **页面切换滚动重置**：管理后台内容高度是动态的，从内容多的页面滚到底后切到内容少的页面时窗口滚动残留导致视图错位；切换页面一律回到顶部并 `history.scrollRestoration='manual'`（五站同步）。

### 性能 / 稳定性
- **应用启动自动清理整页缓存**：磁盘整页缓存 + 内存 LRU 启动即清，避免发版后命中旧页面。`4f3956d`
- **缩略图 OOM 修复**：限制缩略图并发、JPEG 解码降采样，修复杭州站 OOM 导致的 502；进一步改为单 worker 队列串行生成，五站内存配置统一。`302c23d`, `5e198cf`
- **五站代码提速与后台体验优化**：后台各页面展示本次请求响应耗时（非滑动窗口均值）、健康检查、移动端样式适配等。`e81fc68`

### 部署 / K8s
- **零停机发版改造**：去掉 hostPort 改 Service ClusterIP，YAML 成为唯一真相源，`RollingUpdate(maxUnavailable:0, maxSurge:1)`，就绪/存活探针 8s→18s，依赖链路同步调整。`e32a9e6`
- **502 排查与运维命令写入 README**（队列方案，不增加内存）。`5e198cf`
- **文档同步**：删除从未读取的 `sites/*/site.json`（全存数据库）；根 README 与五站 README 融合重写，补充 Drone 30080 界面地址与自动部署链路介绍。`fc781d7`
- 清理误提交的临时诊断脚本。`07467a4`

## v2.3.3 — 2026-11-26

### 修复
- **Drone push 自动触发失效（`Cannot find repository`）**：Gitee 仓库显示名为中文 `Techo一杯茶轻量自托管站群CMS`，而 Drone 库 `repos.repo_name` 存的是路径 `techo`。Gitee webhook payload 的 `repository.name` 用显示名、Drone 的 Gitee 驱动据此查库（`convertHookRepository` 里 `Name: from.Name`），两者不匹配导致 push 返回 `Cannot find repository` 且不产生 build。抓包对比 payload 确认后，通过 Gitee API `PATCH /repos/donghaichen/techo {"name":"techo"}` 把**显示名改为 `techo`**（路径与 clone 地址不变）。验证：push 后 Drone 产生 `build_id=1`（event=push，46 秒 success），部署日志显示五站滚动更新 + 健康校验全 200。
- **确认 webhook 现状**：Gitee 仓库当前仅剩一条 WebHook（`:30080/hook`，Drone 的），旧的 `:8300/hook` 链路已不存在，`DRONE_WEBHOOK_SECRET` 依旧无需配置（见 v2.3.2 决策）。
- `k8s/DRONE.md` 补充「显示名必须与 `repo_name` 一致」的警告与对应排障条目。

### 说明
- 验证过程中产生两个空提交（`a96d669`、`b181612`，均为 `chore:` 验证 push 触发），无代码改动。

## v2.3.2 — 2026-11-26

### 变更
- **CI 收口为 Drone 单一入口**：Gitee 仓库删除直连 `:8300/hook` 的旧 WebHook，push 统一由 Drone `:30080/hook` 接收 → 自动 build → curl 8300 → `k3s-deploy.sh`。8300 接收器服务保留（是 Drone 的下游执行器，不可删）。
- `.drone.yml` 增加 `trigger: event: [push]`（手动 Run pipeline 也产生 push 事件），避免 PR 事件触发生产部署；日志标记改为带触发方式。
- `k8s/DRONE.md` 更新为「手动 + push 自动」双入口架构说明，并补充 WebHook 验签机制说明。

### 决策记录
- **不配置 `DRONE_WEBHOOK_SECRET`**：Drone 对入站 Gitee 推送的验签使用每仓库独立的 `repo.Signer`（激活仓库时自动生成并写入 Gitee WebHook 密码，当前 `techo` 已生效）；`DRONE_WEBHOOK_SECRET` 只用于 Drone 出站系统 WebHook，对入站链路无效。依据 `go-scm/scm/driver/gitee/webhook.go` 的 `Parse()`。

## v2.3.1 — 2026-11-26

### 修复
- **模板环境缓存失效（五站）**：`app/pages/render.py` 的 `cfg_root_env()` 只从 `_ENV` 读取却从未写回，且 `register_env()` 在全项目无调用点，导致每次整页缓存未命中都会重新 `build_env()` 并重新编译全部 Jinja 模板。改为构建后写回 `_ENV[key]`（按 站点 + 主题 维度缓存，进程内常驻）。
- **缓存键覆盖排查结论**：对全部前台页面（首页、栏目列表、单页、详情、搜索、留言、sitemap）逐一审计 `cache_key` 赋值与使用路径。此前已修复的栏目页 `cache_key` 被 `listv2:` 覆盖问题（见 v2.3.0）无同类残留；`cfg_root_env()` 内部的局部 `cache_key` 属独立函数作用域，与整页缓存键无冲突。缩略图 `thumb.py` 的缓存路径由 `sha1(rel+process)` 生成并带 mtime stamp，无覆盖风险。

## v2.3.0 — 2026-11-26

### 修复
- **栏目列表页整页缓存失效**：`render.py` 中列表数据缓存键误写为 `cache_key`，覆盖了上方的整页缓存键 `oss34:路径`，导致栏目页整页缓存永远写不进去、每次全量渲染。改用独立变量 `list_cache_key`，栏目页耗时从约 100ms 降至 3ms。`9f51e2f`

### 性能
- **延迟创建 DB Session**：缓存命中路径完全不创建数据库会话（首页/详情等），零 DB 对象开销；`finally` 中按 `db is not None` 判空关闭。`054fc77`
- **整页缓存内存 LRU + 预压缩 gzip**：`cache.py` 新增 `_page_mem`（每站 96 条），命中时零磁盘 IO、零压缩 CPU，直接返回原始 HTML 与预压缩字节。`8448803`

## v2.2.1 — 2026-11-26

### 新功能
- **部署脚本同步默认 favicon**：`k8s/k3s-deploy.sh` 幂等复制仓库根目录 `logo.svg` 到五站 `storage/uploads/site-logo.svg`，并将数据库 `site_favicon` 设为 `/uploads/site-logo.svg`。`93fd6e3`

### 修复
- **全站默认 favicon 统一**：五站六主题 + 后台 + 仓库源图统一为 `logo.svg`；`/favicon.ico` 优先跳转 `img/favicon.svg`。`c5fdc71`

## v2.2.0 — 2026-11-26

### 安全
- **dashboard 接口鉴权**：五站 `content/router.py` 的 `/dashboard` 补 `current_admin` 依赖，未授权返回 401。`d91b754`

### 新功能
- **响应耗时全链路可观测**：新增 `core/perf.py`（`PerfStats` 滑动窗口 + `ResponseTimeMiddleware`），所有响应注入 `X-Response-Time`；健康检查 `/api/health`、后台 dashboard、压测脚本 `scripts/bench.py` 三处展示 avg/P50/P95/P99/max。`27fb90e`

## v2.1.0 — 2026-11-26

### 性能
- **前台路由改同步 + gzip 降级**：解除同步阻塞事件循环的问题；`GZipMiddleware` 设 `compresslevel=1`；`uploads` 长缓存、SQLite WAL、去掉 CPU 限流。`d50460e`, `91f4ddf`

### 运维 / CI
- **Drone CI 接入**：新增 `.drone.yml`（手动 pipeline）、`k8s/drone.yaml`、`k8s/install-drone.sh`、`scripts/nginx/drone.conf.example`、`k8s/DRONE.md`。修复 Drone 端口坑：容器端口与 hostPort 统一为 30080，并设 `DRONE_SERVER_PORT=:30080`。
- **Gitee Go 流水线配置**：`.workflow/ci.yml` 手动触发，复现现有部署脚本（仓库脚本复制到 `/tmp` 执行，避免 `git reset --hard` 自覆盖）。`b004ce9` 等 6 次更新

## v2.0.0 — 2026-11-25

### 新功能
- **五站官网 CMS 初始化**：FastAPI + 极简 K3s 容器化，五站完全独立可单独部署。`0464235`
- **五站收拢到 `sites/` 目录**：部署脚本简化为轻量数据卷检查。`1f4cad4`

### 运维
- **凭据自动生成**：`k8s/secrets/` 自动生成全部凭据并登记 `credentials.txt`；Dashboard 去掉 Basic Auth，文档移除敏感信息。`95f58e2`
- **容器管理界面切换为 KubePi**（中文面板），旧 Dashboard 停用备援；`--enable-insecure-login` 修复 HTTP 下登录态，csrf secret 自动生成。`070ef5f`, `66a2145`, `94308a9`
- **KubePi 改密结果用新密码实际登录验证**，避免误报。`f1814ee`
- **发版记录**：commit 写入修订历史注记 + `release-history.txt` 发版清单，修订列表直接显示提交说明。`e5e5336`, `858ab17`
- **运维入口速查文档**：Dashboard / webhook / SSH / 日志章节。`c0b392b`, `992368e`

### 前台 / 主题
- **首页版块调整**：徐州加精选案例并调整版块顺序，各站案例/服务/资讯数量更新，杭州服务改卡片列表；徐州卡片八色、杭州无锡卡片配图，五主题标题简介超出隐藏。`bb208bd`, `456944e`
- **未到发布时间的内容前台不显示**；前台时间统一显示发布时间（无则回落创建时间）。

### 文档
- `README.md` 与五站 README 更新。`dbdd505`
