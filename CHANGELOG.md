# 变更记录（CHANGELOG）

本项目为「五站官网 CMS」：FastAPI + SQLite + Jinja2 SSR，五站（南京/杭州/合肥/无锡/徐州）完全独立，极简 K3s 容器化部署。

本文件记录每一次功能性修改、性能优化与修复，便于追溯。五站代码目录 `sites/<城市>/src/app` 完全同步，任何代码改动需同时应用到五个副本（改动后用 `md5 -q sites/*/src/app/<文件>` 校验一致性）。

格式约定：按版本倒序排列（最新在上），每条包含日期、类型标签与变更说明，并在末尾标注对应 Git 提交短哈希。

---

## v2.3.2 — 2026-11-26（当前）

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
