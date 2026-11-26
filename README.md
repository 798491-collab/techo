# Techo 一杯茶轻量自托管站群 CMS

> **简约轻量，低资源开销，几分钟就能完成搭建的自托管站群 CMS**

Techo 由 Tea 和 Echo 组成，读音 /ˈtiːkoʊ/。**Tea 呼应一杯茶的简约理念**，Echo 代表内容传递与共鸣反馈。它主打简约轻量、极易搭建，是一套自托管站群 CMS：**易安装**——支持二进制包、Docker、系统包多种部署方式；**跨平台**——Python 支持的 Windows、Mac、Linux、ARM 均可运行；**轻量级**——一台廉价树莓派就能满足最低运行需求。

本仓库为 Techo 的五站点实装：五个站点、五套完全不同的主题、五套独立前后台。每个站点都是**完全独立、自包含**的系统——自带全套后端代码、管理后台前端、主题、脚本与数据目录，**不依赖任何目录外的共享代码**，整个站点目录可直接拷贝到任意位置独立部署运行。

## 特性

- **完全独立**：每个站点代码拷到任意目录都能独立运行，五站代码互不干扰、不共享
- **数据隔离**：各自 FastAPI 实例、SQLite、文件缓存、上传目录、主题，配置只读本站 `site.json`
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

- 五个站点各自独立 Deployment（namespace `pysite`），`hostNetwork: true` 直接占用 8101–8105
- 共用一个 Python 镜像（`python:3.10-slim`），依赖从宿主机以 hostPath 挂入
- 数据卷：各站 `storage/`（site.db / seed.json / uploads / cache / logs / sessions / temp）在站点目录内随 hostPath 持久化

### 自动部署

- Git 推送自动部署：仓库 push → Gitee WebHook → 服务器 webhook 接收器 → 自动执行部署脚本
- 部署脚本自动完成代码更新、数据卷检查、健康检查、滚动更新

### 容器管理界面（KubePi）

- 入口：`http://<服务器IP>:10000/`
- 账号：`admin` + 随机密码（部署时自动生成）
- 可视化管理 Pod / Deployment / 日志 / 终端 / 重启

### 常用命令

```bash
# 查看 Pod 状态
kubectl -n pysite get pod -o wide

# 查看日志
kubectl -n pysite logs deploy/pysite-nanjing --tail=50

# 重启站点
kubectl -n pysite rollout restart deploy/pysite-nanjing

# 回滚站点
kubectl -n pysite rollout undo deploy/pysite-nanjing
```

## 目录结构

```
py-site/
├── sites/                    # 五个站点，每个都是完全独立系统
│   ├── nanjing/
│   │   ├── src/app/          # 配置 / 数据库 / 模型 / 缓存 / 安全 / 应用工厂
│   │   ├── admin/            # 管理后台静态前端
│   │   ├── themes/           # 主题模板 / 静态资源 / 组件宏
│   │   ├── scripts/          # 站点脚本：run.py / start.py
│   │   ├── site.json         # 站点配置
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