# Techo 站群 CMS

> 
> **一杯茶理念 · 简约轻量 · 极易搭建的自托管站群CMS**

Techo 由 Tea 和 Echo 组成，读音 /ˈtiːkoʊ/。**Tea 呼应一杯茶的简约理念**，Echo 代表内容传递与共鸣反馈，延续 Typecho 的命名巧思。
它主打简约轻量、极易搭建，是一套自托管站群 CMS：**易安装**——支持二进制包、Docker、系统包多种部署方式；**跨平台**——Python 支持的 Windows、Mac、Linux、ARM 均可运行；**轻量级**——一台廉价树莓派就能满足最低运行需求。

本仓库为 Techo 的五站点实装：五个站点、五套完全不同的主题、五套独立前后台。每个站点都是**完全独立、自包含**的系统——自带全套后端代码、管理后台前端、主题、脚本与数据目录，**不依赖任何目录外的共享代码**，整个站点目录可直接拷贝到任意位置独立部署运行。

## 目录

- [站点与端口](#%E7%AB%99%E7%82%B9%E4%B8%8E%E7%AB%AF%E5%8F%A3) · [后台账号与密钥](#%E5%90%8E%E5%8F%B0%E8%B4%A6%E5%8F%B7%E4%B8%8E%E5%AF%86%E9%92%A5) · [本地启动](#%E6%9C%AC%E5%9C%B0%E5%90%AF%E5%8A%A8) · [单站独立部署](#%E5%8D%95%E7%AB%99%E7%8B%AC%E7%AB%8B%E9%83%A8%E7%BD%B2)
- [服务器部署（K3s）](#%E6%9C%8D%E5%8A%A1%E5%99%A8%E9%83%A8%E7%BD%B2k3s) · [运维入口速查](#%E8%BF%90%E7%BB%B4%E5%85%A5%E5%8F%A3%E9%80%9F%E6%9F%A5) · [目录结构](#%E7%9B%AE%E5%BD%95%E7%BB%93%E6%9E%84)
- [关键设计](#%E5%85%B3%E9%94%AE%E8%AE%BE%E8%AE%A1) · [富文本与表单能力](#%E5%AF%8C%E6%96%87%E6%9C%AC%E4%B8%8E%E8%A1%A8%E5%8D%95%E8%83%BD%E5%8A%9B) · [管理后台 UI/UX](#%E7%AE%A1%E7%90%86%E5%90%8E%E5%8F%B0-uiux)
- [后台功能模块](#%E5%90%8E%E5%8F%B0%E5%8A%9F%E8%83%BD%E6%A8%A1%E5%9D%97) · [数据模型](#%E6%95%B0%E6%8D%AE%E6%A8%A1%E5%9E%8B41-%E5%BC%A0%E8%A1%A8) · [数据入库](#%E6%95%B0%E6%8D%AE%E5%85%A5%E5%BA%93) · [API](#api) · [主题风格](#%E4%B8%BB%E9%A2%98%E9%A3%8E%E6%A0%BC%E4%BA%94%E5%A5%97%E5%AE%8C%E5%85%A8%E4%B8%8D%E5%90%8C)

## 站点与端口

| 站点 | 站点主体 | 端口 | 前台 | 后台 | 主题风格 |
| --- | --- | --- | --- | --- | --- |
| nanjing | 南京筑韬建筑工程有限公司 | 8101 | `http://127.0.0.1:8101/` | `/admin/` | 深蓝商务 · 大图 Banner |
| hefei | 合肥筑骋建筑工程咨询有限公司 | 8102 | `http://127.0.0.1:8102/` | `/admin/` | 橙色活力 · 卡片式 |
| xuzhou | 徐州玖硕建筑工程咨询有限公司 | 8103 | `http://127.0.0.1:8103/` | `/admin/` | 红色稳重 · 政务风 |
| wuxi | 无锡君鑫建筑工程咨询有限公司 | 8104 | `http://127.0.0.1:8104/` | `/admin/` | 墨绿高端 · 杂志排版 |
| hangzhou | 杭州志俞建筑工程咨询有限公司 | 8105 | `http://127.0.0.1:8105/` | `/admin/` | 黑白极简 · 科技几何 |

- 各站域名属敏感信息，不入库；以服务器 nginx 反代配置（`scripts/nginx/`，仅本地保留）与各站 `site.json` 为准。
- 每个站点目录内含独立说明 `README.md`（单站启动 / 独立部署 / 目录结构 / 运维）。

## 后台账号与密钥

- 后台初始账号：`admin`，访问 `域名/admin/`（建议带结尾斜杠；`/admin` 会 307 跳转到 `/admin/`）。
- 站点 `.env` 不存在时，首次启动自动生成随机密钥（SECRET_KEY，64 位十六进制）与后台初始密码（24 位随机串），密码在控制台打印一次，请立即保存；生成后落盘固定不变，已有值不会被覆盖。也可预先在 `.env` 或环境变量 `PYSITE_SECRET` / `PYSITE_ADMIN_PASSWORD` 中指定。
- 首次建库后密码固化于数据库（存 hash），后续改密请在后台「个人资料」操作。
- ⚠️ 删除 `.env` 后重启会重新生成新密钥，旧登录态与旧后台密码都会失效。
- `.env` 不入 Git；真实凭据只存服务器本地或团队密码管理器，任何入库文件不得出现真实值。

## 本地启动

> 
> 秉承极易搭建的设计理念，本地上手简单快捷。

进入对应站点的 `scripts` 目录（如 `sites/nanjing/scripts/`）：

| 方式 | 操作 |
| --- | --- |
| Windows 双击 | `start.bat` 启动（自动打开后台）／`stop.bat` 停止／`status.bat` 查看状态 |
| 命令行 | `python start.py`（启动并打开浏览器）／`--no-open` 不开浏览器／`status`／`stop` |
| 直接运行 | `python run.py`（前台阻塞，Ctrl+C 停止） |

其余站点同理：`cd sites/hefei/scripts`、`cd sites/xuzhou/scripts`、`cd sites/wuxi/scripts`、`cd sites/hangzhou/scripts`。

启动脚本特性：端口占用预检（避免重复启动）、健康检查等待就绪、依赖自动检查安装（自动探测 pypi / 清华 / 阿里 / 中科大镜像并选最快）、本站独立日志 `storage/logs/run.log`、PID 记录用于可靠停止。

## 单站独立部署

> 
> 简约轻量，单站目录完全自包含，低配置机器也可流畅运行。

把 `sites/nanjing/`（或任意一站）拷贝到任意机器、任意目录即可：

1. `cd nanjing/scripts && python start.py` —— 首次运行自动在本站目录创建 `.venv` 并安装依赖（fastapi、uvicorn、jinja2、sqlalchemy 等，自动选最快镜像源）；
2. 首次启动自动生成 `.env` 密钥与后台初始密码（控制台打印一次）；
3. 自动建库并写入种子数据（`storage/seed.json`），前后台即可使用。

无需依赖仓库根目录的任何文件。仓库根的 `venv/` 只是服务器 K3s 部署的共享依赖目录，本地单站运行用不到。

## 服务器部署（K3s）

生产环境运行在服务器上的**极简 K3s**（v1.28.5+k3s1，已禁用 traefik / metrics-server / servicelb / local‑storage，系统 Pod 仅 CoreDNS；2 核 / 1.9G 内存承载五个站点 + KubePi + webhook，充分发挥 Techo 轻量特性）。

### 架构

- 五个站点各自独立 Deployment（namespace `pysite`），`hostNetwork: true` 直接占用 8101–8105，宿主机 nginx 反代配置零改动；
- **共用一个镜像**（`python:3.10‑slim`，免构建）：Python 依赖从宿主机 `/www/wwwroot/pysite/venv/lib/python3.10/site‑packages` 以只读 hostPath 挂入，通过 `PYTHONPATH` 生效；站点目录整体挂载到容器 `/app`；
- **数据卷**：各站 `storage/`（site.db / seed.json / uploads / cache / logs / sessions / temp / pycache）在站点目录内随 hostPath 持久化，**部署 / 重启 / 滚动更新永不覆盖**；
- 代码目录：服务器 `/www/wwwroot/pysite/`（Git 仓库根）；kubeconfig `/etc/rancher/k3s/k3s.yaml`。

### Git 推送自动部署（已生效）

- 仓库：`git@gitee.com:donghaichen/py‑site.git`（分支 `main`；服务器部署公钥只读 pull，无法 push，推送在开发机执行，走 HTTPS 凭据）；
- **触发链路**：`git push` → Gitee WebHook → 服务器 K3s 内 `webhook‑receiver` Pod（端口 8300，纯标准库，limits 64Mi）→ nsenter 进宿主机执行 `/root/k3s‑deploy.sh`；
- **WebHook 地址**（Gitee 仓库 → 管理 → WebHooks，Push 事件）：`http://<服务器IP>:8300/hook?token=<WebHook Token>`；
- 部署脚本位于仓库外 `/root/k3s‑deploy.sh`（不会被 `git reset` 覆盖；源码备份在仓库 `k8s/k3s‑deploy.sh`），流程：
0. **凭据自动配置**：WebHook Token、KubePi 管理员密码、五站后台密码缺失时随机生成，统一写入服务器 `k8s/secrets/credentials.txt`（类似 MySQL 安装后打印临时密码）；
  1. `git fetch + reset --hard` 更新代码（`storage/` 被 gitignore，不受影响）；
  2. **数据卷就绪检查**：五站 `sites/<站点>/storage/site.db` 存在且非空，异常立即中止；
  3. **发版记录**：把 commit、提交说明、发版时间写入五站 Deployment 修订历史（KubePi「部署 → 修订历史」可查看每次发版内容并一键回滚），并滚动更新生效；
  4. 健康检查：五站 HTTP 200，失败自动 `rollout undo` 回滚（并记入发版清单）。
- **git push 即部署，无需人工确认**；部署日志 `scripts/k3s‑deploy.log`，webhook 日志 `scripts/webhook.log`，发版清单 `scripts/release‑history.txt`。

### 容器管理界面（KubePi）

- 入口：`http://<服务器IP>:10000/`（nginx 反代 → NodePort 30110，反代配置 `/www/server/panel/vhost/nginx/k8s‑dashboard.conf`）；
- **登录**：账号 `admin`，密码为部署时自动生成的随机值（部署脚本通过 KubePi API 直接改掉默认 `admin/kubepi`，密码写在服务器 `k8s/secrets/credentials.txt`；若 API 改密未成功，首次登录系统会强制要求设置新密码，双保险杜绝默认密码）；
- **首次使用需导入集群**：左侧「集群管理 → 添加集群」，认证方式选 Token：
  - API 地址：`https://<服务器IP>:6443`
  - Token：服务器 `cat /www/wwwroot/pysite/k8s/secrets/kubepi‑cluster‑token.txt`（有效期 10 年）
  - TLS 校验：跳过（自签证书）
- 中文界面，可视化管理 Pod / Deployment / 日志 / Web 终端 / 重启；数据持久化在宿主机 `/www/wwwroot/pysite/kubepi‑data/`（gitignore）；
- 部署清单在仓库 `k8s/kubepi.yaml`，可 `kubectl apply -f k8s/kubepi.yaml` 重建，详见 `k8s/README.md`。

### 日常维护命令（SSH 执行）

```
kubectl get pods -A                                      # 全部 Pod 状态
kubectl -n pysite get pod -o wide                        # 五站 Pod
kubectl -n pysite logs deploy/pysite‑nanjing --tail=50   # 某站日志
kubectl -n pysite rollout restart deploy/pysite‑nanjing  # 重启某站
kubectl -n pysite rollout restart deploy                 # 重启五站
kubectl -n pysite rollout undo deploy/pysite‑nanjing     # 回滚某站上次变更
tail -f /www/wwwroot/pysite/scripts/k3s‑deploy.log       # 部署日志
```

站点运行日志在容器内 `storage/logs/site.log`，即宿主机 `/www/wwwroot/pysite/sites/<站点>/storage/logs/site.log`。

### 访问方式与备份

- 只启用 HTTP(80)，未开 SSL；必须用域名 `http://...` 访问，IP 访问会落到 nginx 默认站点（正常现象）；
- K3s 自身：API Server 6443（仅本机管理）、KubePi NodePort 30110（经反代 10000 对外）；
- **备份**：五站 `storage/` 目录与各站 `.env` 是全部状态；完整备份（storage + .env + nginx 配置）存放在服务器 `/root/pysite‑backup‑<时间戳>/`，最新备份路径记录在 `/root/.pysite‑latest‑backup`；
- 单站回滚：`kubectl -n pysite rollout undo deploy/pysite‑<站点名>`。

## 运维入口速查

| 入口 | 地址 | 认证 | 说明 |
| --- | --- | --- | --- |
| **KubePi**（容器管理界面，中文） | `http://<服务器IP>:10000/` | `admin` + 随机密码（部署时自动生成并改掉默认值，见服务器 `k8s/secrets/credentials.txt`） | 现代化中文面板，可视化管理 Pod / Deployment / 日志 / 终端 / 重启；集群首次使用需导入 |
| **Webhook 接收器健康检查** | `http://<服务器IP>:8300/healthz` | 无（token 校验只在 `/hook` 触发时） | 返回 200 = 自动部署链路正常；WebHook Token 同样由 provision 脚本自动生成（`k8s/secrets/webhook‑token.txt`） |
| **SSH 运维（kubectl）** | `ssh root@<服务器IP>` | SSH 凭据 | 登录后 `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml` 再执行 kubectl |
| K3s API Server | `https://<服务器IP>:6443` | kubeconfig 客户端证书 | 仅本机 / 内网管理用，不对公网开放 |
| 五站前台 | `http://<各站域名>/` | — | 必须用域名访问，IP 会落到 nginx 默认站点 |
| 五站后台 | `http://<各站域名>/admin/` | `admin` + 后台密码（部署时自动随机生成） | 密码统一见服务器 `k8s/secrets/credentials.txt`；建议带结尾斜杠 |
| 部署 / webhook 日志 | 服务器 `/www/wwwroot/pysite/scripts/k3s‑deploy.log`、`webhook.log` | SSH | `tail -f` 实时查看 |
| 发版记录 | 服务器 `/www/wwwroot/pysite/scripts/release‑history.txt` | SSH | 每次成功发版一行：时间 + commit + 提交说明 + 作者；也可在 KubePi「部署 → 修订历史」查看并回滚 |

> 
> 服务器 IP、域名、SSH 凭据等真实值不入库。所有凭据（KubePi 管理密码、WebHook Token、五站后台密码）由部署脚本自动随机生成，统一登记在服务器 `k8s/secrets/credentials.txt`（权限 600，gitignore），不写任何系统目录，无需人工改密码。

## 目录结构

```
py‑site/
├── sites/                    # ★ 五个站点，每个都是完全独立系统（可直接整体拷走部署，内含独立 README.md）
│   ├── nanjing/
│   │   ├── src/app/          #   配置 / 数据库 / 模型 / 缓存 / 安全 / 应用工厂 / 各业务模块
│   │   ├── admin/            #   管理后台静态前端（随代码发版，FastAPI 托管）
│   │   ├── themes/           #   主题模板 / 静态资源 / 组件宏
│   │   ├── scripts/          #   站点脚本：run.py / start.py / *.bat / reset_admin / migrate / seed
│   │   ├── site.json         #   站点配置（公司信息 / 主题 / 端口 / 导航 / 轮播）
│   │   ├── .env              #   密钥（不入库，首次启动自动生成）
│   │   └── storage/          #   唯一持久化目录：SQLite / 上传 / 缓存 / 日志 / 会话 / 临时（容器只挂此卷）
│   └── hefei/ xuzhou/ wuxi/ hangzhou/   # 各自同样结构，完全独立
├── k8s/                      # K3s 部署清单：五站 Deployment / KubePi / webhook / 部署脚本与凭据配置
├── scripts/                  # 项目级脚本：nginx 反代配置源、部署日志
├── venv/                     # Python 虚拟环境（服务器 K3s 共享依赖，本地单站运行不需要）
└── README.md                 # 本文档（项目总览 + 部署总说明）
```

**`storage/` 是唯一持久化目录**：数据库、上传、缓存、日志、会话、临时文件全在里面；Git 只提交 `seed.json` 和目录骨架，其余全忽略——生产数据永远不会被部署覆盖。旧目录 `runtime/ var/ uploads/ data/` 已淘汰，代码启动时 `_migrate_legacy` 会把旧目录数据自动迁入 `storage/`（copy 不删，兼容老部署升级）。

**`admin/` 为什么在站点目录而不是 `storage/`**：admin 是随代码发版的管理后台静态前端（FastAPI 托管、Git 版本管理、部署时随代码更新）；storage 是部署永不触碰的数据卷（gitignore）。若把 admin 放进 storage，后台前端将不进 Git、部署也无法更新界面、整体拷贝站点会缺文件。

## 关键设计

- **完全独立**：每个站点代码拷到任意目录都能独立运行，五站代码互不干扰、不共享；
- **数据隔离**：各自 FastAPI 实例、SQLite、文件缓存、上传目录、主题，配置只读本站 `site.json`；
- **后台一致但各自持有**：每站内置一份相同的管理后台静态资源与 API 代码，界面一致、数据独立；
- **CRUD 配置驱动**：后台所有列表复用 `crud.js`，后端返回配置 JSON 驱动渲染，无需逐业务写页面；
- **SQLite + 文件缓存**：零外部依赖，开箱即用，契合简约轻量定位；
- **缓存失效**：后台增删改、切主题、改配置后自动清空站点页面缓存，前台立即生效（整页缓存在 `storage/cache/pages/`，后台、搜索页、在线留言不缓存）；
- **前台列表排序**：新闻 / 案例 / 产品按后台选择的发布时间倒序（置顶优先，无发布时间回落创建时间），后台列表排序与前台一致；未到发布时间的内容前台不显示（定时发布）；
- **前台时间显示**：永远显示发布时间（publish_at），无发布时间回落创建时间。

## 富文本与表单能力

- **wangEditor 富文本**：正文用本地 wangEditor v5（图片上传走 `/api/admin/upload`），前台 HTML 安全渲染；
- **拖拽上传**：封面等图片字段为拖拽 / 点击上传组件，实时预览、可移除；所有文件 / 图片 / 附件表单统一使用 `admin/js/upload.js` 上传组件（缩略图预览列表 + 素材库选择弹窗 + 大图预览 + 头像方形裁剪器）；
- **表单模型可视化编辑**：自定义表单字段一行一个可视化编辑，无需手写 JSON；
- **表单校验**：JustValidate 前端校验，必填字段红色 `*`，提交失败提示具体字段；
- **内容表单精简**：作者自动取当前登录用户、发布时间自动填当前、摘要从正文自动生成；
- **访问别名**：不填时自动按标题拼音或英文生成；
- **产品 / 案例图集**：多图上传，存 extra JSON；
- **上传目录模板**：`{filetype}/{year}{month}/{day}`，可用变量 `{filetype} {year} {month} {day} {datetime} {timestamp} {rand6} {rand8}`，文件名为内容 md5 + 后缀（`src/app/core/services.py::render_save_dir`）；
- **页脚**：备案号链接 `https://beian.miit.gov.cn`，公网安备案号链接 `https://beian.mps.gov.cn/`。

## 管理后台 UI/UX

- **品牌**：企业管理系统 V35.26.1351；双主题（右上角深色 / 浅色切换，localStorage 记忆，全站变量化配色）；
- **G2 图表**：仪表盘内容发布趋势（面积图）、内容模型分布（环形图），主题切换自动重绘；
- **菜单开关**：「系统设置 → 系统开关」一键隐藏站群 / 会员 / 订单 / 评论 / 开发 / 多语言 / 短信 / AI 等菜单组；
- **基础设置**：QQ、微信二维码、ICP 备案号、公网安备案号、统计代码、联系人等；
- **交互**：删除 / 恢复 / 导出 / 退出用带类型图标的确认弹窗；新增 / 编辑在弹窗内完成（点空白处 / ESC 不关闭）；全局 Loading、骨架屏、数字滚动、进场动效；主色按钮文字图标统一白色；
- **H5 自适应**：手机端侧栏抽屉、统计卡两列、图表表格自适应；
- **插件中心**：OSS / COS 云存储插件安装 / 卸载 / 启用 / 配置，「上传设置」可切换上传驱动与水印九宫格位置；
- **主题管理**：卡片 / 列表双视图，五套主题一键启用。

## 后台功能模块

后台共 12 个一级模块、43 个菜单项，全部可用：

| 一级模块 | 二级菜单 |
| --- | --- |
| 仪表盘 | 数据概览、内容模型分布、最近内容、待办统计 |
| 站群管理 | 站点列表、地区库、批量生成、站群同步、站群设置 |
| 内容管理 | 栏目分类、标签管理、文章、产品、案例、内容回收站 |
| 素材库 | 文件列表（图片 / 视频 / 附件）、批量上传 |
| 会员管理 | 会员列表、会员分组、会员等级、余额流水、积分流水 |
| 订单与支付 | 订单列表、退款记录、支付配置 |
| 自定义表单 | 表单模型、提交记录 |
| 评论管理 | 评论列表（待审核 / 通过 / 驳回） |
| 运维工具 | 定时任务、任务日志、备份恢复、SEO 配置（网站地图为系统功能，实时动态生成） |
| 权限管理 | 管理员列表、角色管理、权限节点 |
| 系统设置 | 基础设置、多语言管理、语言包管理、上传设置、短信设置、AI 配置、安全设置、操作日志 |
| 开发管理 | CRUD 管理、内容模型、主题管理、插件管理、开放 API |

左侧菜单 + 顶部导航 + 多 Tab + 弹窗表单 + 侧边筛选 + 批量操作 + 导入导出 + 回收站 / 恢复；菜单由后端 `/api/admin/menu` 动态驱动，超级管理员全可见。

## 数据模型（41 张表）

系统后台（管理员 / 角色 / 权限 / 审计 / 配置 / 素材 / 定时任务 / 任务日志 / 备份）、站群（站点 / 地区 / 站点变量 / 同步记录 / 地区映射）、多语言（语言 / 语言包）、内容（内容类型 / 栏目 / 标签 / 内容 / 多语言子表 / 扩展字段 / 标签关联）、会员（分组 / 等级 / 会员 / 地址 / 收藏 / 足迹 / 余额流水 / 积分流水）、表单（模型 / 记录）、订单库存（SKU / 订单 / 订单项 / 退款 / 库存日志）、评论、留言、设置。

每站一份独立 SQLite，表结构完全相同；软删除表支持回收站 / 恢复 / 彻底删除。

## 数据入库

五家公司资料中的图片、PDF、Word 等文件已全部扫描登记到各自站点的**素材表（media）**（nanjing 4 / hefei 32 / xuzhou 15 / wuxi 2 / hangzhou 17），栏目、内容、表单、公司信息写入对应数据表。后台「素材库」可直接管理；前台 Hero / 推荐 / 案例使用各站真实图片与背景。

## API

- `/api/admin/*` 后台管理接口（登录鉴权，含通用 CRUD、备份、Sitemap 等）
- `/api/frontend/*` 前台公共接口（留言、表单、搜索）
- `/api/health` 健康检查
- `/sitemap.xml` 站点地图（系统内置，按固定页面 + 已启用栏目 + 已发布内容实时生成，不落地静态文件；后台「运维工具 → SEO 配置」只读查看）

## 主题风格（五套完全不同）

1. 南京 · 深蓝商务 + 金色点缀 + 建筑剪影 Banner
2. 合肥 · 橙色活力 + 圆角卡片 + 波浪装饰
3. 徐州 · 红色政务 + 对称庄重 + 金线装饰
4. 无锡 · 墨绿高端 + 杂志排版 + 衬线字体
5. 杭州 · 黑白极简 + 科技网格 + 几何 Logo

每套主题仅由 `base.html` / `index.html` / `style.css` 三个文件构成，页面逻辑全部复用公共模板与组件宏。`uploads` 与 `theme‑libs` 由 nginx 直出（sendfile 零拷贝），应用侧保留同名路由作本地开发兜底；反代配置见 `scripts/nginx/*.conf`。
