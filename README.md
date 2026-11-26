# Techo 一杯茶轻量自托管站群 CMS

> **简约轻量，低资源开销，几分钟就能完成搭建的自托管站群 CMS**

Techo 由 Tea 和 Echo 组成，读音 /ˈtiːkoʊ/。**Tea 呼应一杯茶的简约理念**，Echo 代表内容传递与共鸣反馈。它主打简约轻量、极易搭建，是一套自托管站群 CMS：**易安装**——支持二进制包、Docker、系统包多种部署方式；**跨平台**——Python 支持的 Windows、Mac、Linux、ARM 均可运行；**轻量级**——一台廉价树莓派就能满足最低运行需求。

本仓库为 Techo 的五站点实装：五个站点、五套完全不同的主题、五套独立前后台。每个站点都是**完全独立、自包含**的系统——自带全套后端代码、管理后台前端、主题、脚本与数据目录，**不依赖任何目录外的共享代码**，整个站点目录可直接拷贝到任意位置独立部署运行。

## 特性

- **完全独立**：每个站点代码拷到任意目录都能独立运行，五站代码互不干扰、不共享
- **数据隔离**：各自 FastAPI 实例、SQLite、文件缓存、上传目录、主题；站点配置全部读数据库（后台「系统配置」在线修改），密钥只放各站 `.env`
- **SQLite + 文件缓存**：零外部依赖，开箱即用，契合简约轻量定位
- **跨平台**：Windows、Mac、Linux、ARM 均可运行
- **轻量级**：一台廉价树莓派就能满足最低运行需求
- **一键部署**：支持本地启动、Docker、K3s 等多种部署方式

## 站点与端口

| 站点 | 站点主体 | 端口 | 主题风格 |
| --- | --- | --- | --- |
| nanjing | 南京筑韬建筑工程有限公司 | 8101 | 深蓝商务 · 大图 Banner |
| hefei | 合肥筑骋建筑工程咨询有限公司 | 8102 | 橙色活力 · 卡片式 |
| xuzhou | 徐州玖硕建筑工程咨询有限公司 | 8103 | 红色稳重 · 政务风 |
| wuxi | 无锡君鑫建筑工程咨询有限公司 | 8104 | 墨绿高端 · 杂志排版 |
| hangzhou | 杭州志俞建筑工程咨询有限公司 | 8105 | 黑白极简 · 科技几何 |

## 快速启动

### 本地启动

进入对应站点的 `scripts` 目录（如 `sites/nanjing/scripts/`）：

**Windows 双击**：
- `start.bat` - 启动（自动打开后台）
- `stop.bat` - 停止
- `status.bat` - 查看状态

**命令行**：
```bash
python start.py          # 启动并打开浏览器
python start.py --no-open  # 启动但不开浏览器
python start.py status   # 查看状态
python start.py stop     # 停止
```

其余站点同理：`cd sites/hefei/scripts`、`cd sites/xuzhou/scripts`、`cd sites/wuxi/scripts`、`cd sites/hangzhou/scripts`。

### 后台账号与密钥

- 后台初始账号：`admin`，访问 `域名/admin/`（建议带结尾斜杠）
- 站点 `.env` 不存在时，首次启动自动生成随机密钥（SECRET_KEY，64 位十六进制）与后台初始密码（24 位随机串），密码在控制台打印一次，请立即保存
- 也可预先在 `.env` 或环境变量 `PYSITE_SECRET` / `PYSITE_ADMIN_PASSWORD` 中指定
- ⚠️ 删除 `.env` 后重启会重新生成新密钥，旧登录态与旧后台密码都会失效

### 单站独立部署

把 `sites/nanjing/`（或任意一站）拷贝到任意机器、任意目录即可：

1. `cd nanjing/scripts && python start.py` —— 首次运行自动在本站目录创建 `.venv` 并安装依赖
2. 首次启动自动生成 `.env` 密钥与后台初始密码（控制台打印一次）
3. 自动建库并写入种子数据，前后台即可使用

无需依赖仓库根目录的任何文件。

## 服务器部署（K3s）

生产环境可部署在极简 K3s 上（2 核 / 1.9G 内存承载五个站点 + KubePi + webhook）。

### 架构

- 五个站点各自独立 Deployment（namespace `pysite`）+ 独立 **ClusterIP Service**（固定 IP `10.43.100.101`–`.105`，端口 8101–8105）
- **不再使用 `hostNetwork` / `hostPort`**：Pod 用集群 IP，nginx 反代到 Service 的 ClusterIP；端口不再与宿主机绑定，无冲突风险
- 更新策略为 **RollingUpdate（`maxUnavailable: 0`）**：新旧 Pod 并存、由 Service 平滑切流，发版**全程无 502**
- 共用一个 Python 镜像（`python:3.10-slim`），依赖从宿主机以 hostPath 挂入
- 数据卷：各站 `storage/`（site.db / seed.json / uploads / cache / logs / sessions / temp）在站点目录内随 hostPath 持久化
- 仓库 `k8s/deploy-*.yaml`、`service-*.yaml`、`scripts/nginx/*.conf` 是**唯一真相源**：每次部署 `kubectl apply`，线上配置（resources / 探针 / 策略）自动与仓库对齐，不再漂移

### 自动部署（Drone CI + Webhook，已上线）

- **Drone CI 界面（30080）**：`http://45.91.139.246:30080` —— 用 Gitee 账号登录，可查看每次 push 的构建记录与日志、手动触发重新构建；健康检查 `http://127.0.0.1:30080/healthz`（服务器本机）
- **完整链路**：仓库 push → Gitee WebHook（唯一一条，指向 `http://45.91.139.246:30080/hook`）→ Drone 构建（Builds 留痕可追溯）→ `curl 127.0.0.1:8300/hook` → 服务器 webhook 接收器（nsenter 进入宿主机执行）→ `k8s/k3s-deploy.sh`
- **部署脚本**：`apply` Service → `apply` Deployment（注入 commit 注记）→ 同步 nginx 反代并 reload → 等待就绪 → 经 ClusterIP 健康检查 → 失败自动 `rollout undo` 回滚
- 部署日志：`scripts/k3s-deploy.log`（宿主机）+ `scripts/webhook.log`（接收器）；Drone 配置详见 `k8s/DRONE.md`

### 容器管理界面（KubePi）

- 入口：`http://<服务器IP>:10000/`
- 账号：`admin` + 随机密码（部署时自动生成）
- 可视化管理 Pod / Deployment / 日志 / 终端 / 重启

### 常用运维命令

```bash
# ---------- Pod / Deployment ----------
kubectl -n pysite get pod -o wide                          # Pod 状态、RESTARTS 次数
kubectl -n pysite get deploy                               # 副本与可用状态
kubectl -n pysite describe pod <pod名>                     # 重点看 Last State / Reason（OOMKilled 等）
kubectl -n pysite logs deploy/pysite-nanjing --tail=50     # 站点日志
kubectl -n pysite logs <pod名> --previous --tail=80        # 崩溃前一份日志
kubectl -n pysite get svc                                  # 五站 ClusterIP（10.43.100.101-.105）
kubectl -n pysite rollout restart deploy/pysite-nanjing    # 重启站点（RollingUpdate，无 502）
kubectl -n pysite rollout undo deploy/pysite-nanjing       # 回滚上一版本
kubectl -n pysite delete pod -l app=pysite-nanjing --wait=true  # 强制重建 Pod
kubectl -n pysite get events --sort-by=.metadata.creationTimestamp | tail -30

# ---------- 日志 ----------
tail -f /www/wwwlogs/hangzhouzhiyu.net.error.log                     # nginx 反代错误（502 根因线索）
tail -f /www/wwwroot/pysite/sites/hangzhou/storage/logs/site.log      # 应用访问日志
tail -f /www/wwwroot/pysite/scripts/k3s-deploy.log                    # 部署日志
tail -f /www/wwwroot/pysite/scripts/webhook.log                       # webhook / Drone 触发日志

# ---------- 健康（经 ClusterIP，不再有宿主机 810x 监听）----------
for i in 101 102 103 104 105; do p=$((8100 + i - 100)); curl -s -o /dev/null -w "10.43.100.$i:$p %{http_code}\n" --max-time 5 http://10.43.100.$i:$p/; done
kubectl -n pysite get deploy pysite-hangzhou -o jsonpath='{.spec.template.spec.containers[0].resources}'
kubectl -n pysite get deploy pysite-hangzhou -o jsonpath='{.spec.strategy}'               # 更新策略
kubectl -n pysite get deploy pysite-hangzhou -o jsonpath='{.spec.template.spec.containers[0].readinessProbe.initialDelaySeconds}'  # 就绪探针延迟

# ---------- 从外部探测 ----------
# 本机若设置了 HTTP_PROXY，必须加 --noproxy '*'，否则代理自身故障会伪报 502
curl --noproxy '*' -H 'Host: www.hangzhouzhiyu.net' http://<服务器IP>/
```

### 502 故障排查实录（2026-11-26）

**现象**：`https://www.hangzhouzhiyu.net/admin/` 返回 502，其余四站正常。

**排查链路（由外到内）**：

1. 外层响应头 `Server: cloudflare` + `error code: 502` → Cloudflare 回源失败，问题在源站。
2. 源站 nginx 间歇 502，错误日志为 `connect() failed (111: Connection refused) while connecting to upstream` 与 `upstream prematurely closed connection`。
3. 直连应用 `http://127.0.0.1:8105/` 稳定 200 → 应用本身能服务，怀疑 Pod 反复重启。
4. `kubectl -n pysite get pod` 显示 `pysite-hangzhou` 重启 5 次，其他站 0 次。
5. `kubectl describe pod` 显示 `Last State: Terminated / Reason: OOMKilled / Exit Code: 137`；`dmesg | grep -i oom` 确认容器 cgroup 内存耗尽（`anon-rss` 约 259Mi，限制 256Mi）。
6. 触发场景：崩溃前 nginx 日志密集出现 `/uploads/image/...?x-oss-process=image/resize,m_fill,w_120,h_80/...webp`（后台文章列表缩略图）。杭州站最大原图 9.5MB / 6000px 级，Pillow 解码一张 RGB 约 72MB；uvicorn 把同步路由放进线程池并发处理十几张，峰值内存打爆 256Mi → 容器被杀 → 重启窗口内 nginx 502。

**修复（不增加内存，五站资源配置保持一致）**：

- `src/app/media/thumb.py`：JPEG 在解码阶段用 `im.draft()` 降采样（6000×4000 → 750×500，解码内存 72MB → 1.1MB）；缩略图处理改为**单 worker 线程池队列**串行执行，同一时刻内存里只有一张待处理图；命中磁盘缓存的请求不排队。
- 五站 `memory limit` 均保持 256Mi，不为单站加内存。
- 验证：6 并发请求下处理峰值并发为 1、全部成功；`pytest tests/ -q` 7 passed；部署后五站 HTTP 200、Pod 重启计数归零。

## 目录结构

```
py-site/
├── sites/                    # 五个站点，每个都是完全独立系统
│   ├── nanjing/
│   │   ├── src/app/          # 配置 / 数据库 / 模型 / 缓存 / 安全 / 应用工厂
│   │   ├── admin/            # 管理后台静态前端
│   │   ├── themes/           # 主题模板 / 静态资源 / 组件宏
│   │   ├── scripts/          # 站点脚本：run.py / start.py
│   │   ├── .env              # 密钥（首次启动自动生成）
│   │   └── storage/          # 唯一持久化目录：SQLite / 上传 / 缓存 / 日志
│   └── hefei/ xuzhou/ wuxi/ hangzhou/   # 各自同样结构
├── k8s/                      # K3s 部署清单
├── scripts/                  # 项目级脚本
└── README.md                 # 本文档
```

**`storage/` 是唯一持久化目录**：数据库、上传、缓存、日志、会话、临时文件全在里面。生产数据永远不会被部署覆盖。

## API

- `/api/admin/*` - 后台管理接口（登录鉴权，含通用 CRUD、备份、Sitemap 等）
- `/api/frontend/*` - 前台公共接口（留言、表单、搜索）
- `/api/health` - 健康检查
- `/sitemap.xml` - 站点地图

## 技术栈

- **后端**：Python 3.10 + FastAPI + SQLAlchemy
- **数据库**：SQLite
- **前端**：HTML + CSS + JavaScript（原生）
- **富文本**：wangEditor v5
- **图表**：G2
- **部署**：K3s + Docker

## 主题风格（五套完全不同）

1. **南京** · 深蓝商务 + 金色点缀 + 建筑剪影 Banner
2. **合肥** · 橙色活力 + 圆角卡片 + 波浪装饰
3. **徐州** · 红色政务 + 对称庄重 + 金线装饰
4. **无锡** · 墨绿高端 + 杂志排版 + 衬线字体
5. **杭州** · 黑白极简 + 科技网格 + 几何 Logo

## 许可证

MIT License