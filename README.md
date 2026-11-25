# 站群 CMS · 五个独立官网

五家公司官网，五套完全不同主题，五套独立前后台。每个站点都是**完全独立、自包含**的系统：
自带全套后端代码、管理后台前端、主题、脚本与数据目录，**不依赖任何目录外的共享代码**，
整个站点目录可直接拷贝到任意位置独立部署运行。

## 站点与端口

| 站点 | 公司 | 端口 | 域名 | 前台 | 后台 | 主题风格 |
| --- | --- | --- | --- | --- | --- | --- |
| nanjing | 南京筑韬建筑工程有限公司 | 8101 | nanjingzhutao.com | http://127.0.0.1:8101/ | /admin/ | 深蓝商务 · 大图 Banner |
| hefei | 合肥筑骋建筑工程咨询有限公司 | 8102 | hefeizhupin.com | http://127.0.0.1:8102/ | /admin/ | 橙色活力 · 卡片式 |
| xuzhou | 徐州玖硕建筑工程咨询有限公司 | 8103 | xuzhoujiushuo.com | http://127.0.0.1:8103/ | /admin/ | 红色稳重 · 政务风 |
| wuxi | 无锡君鑫建筑工程咨询有限公司 | 8104 | wuxijunxin.com | http://127.0.0.1:8104/ | /admin/ | 墨绿高端 · 杂志排版 |
| hangzhou | 杭州志俞建筑工程咨询有限公司 | 8105 | hangzhouzhiyu.net | http://127.0.0.1:8105/ | /admin/ | 黑白极简 · 科技几何 |

> 每个站点目录内有独立的详细说明 `README.md`（单站启动 / 独立部署 / 目录结构 / 运维）。

## 后台账号与密钥

- 后台初始账号：`admin`（访问 `域名/admin/`，建议带结尾斜杠；`/admin` 会 307 跳转到 `/admin/`）。
- 站点 `.env` 不存在时，首次启动自动生成随机密钥（SECRET_KEY 64 位十六进制）与后台初始密码
  （24 位随机串），密码在控制台打印一次请立即保存；生成后落盘固定不变，已有值不会被覆盖。
  也可预先在 `.env` 或环境变量 `PYSITE_SECRET` / `PYSITE_ADMIN_PASSWORD` 中指定。
- 首次建库后密码固化于数据库（存 hash），后续改密请在后台「个人资料」操作。
- ⚠️ 删除 `.env` 后重启会重新生成新密钥，旧登录态与旧后台密码都会失效。
- `.env` 不入 Git；真实凭据只存服务器本地或团队密码管理器，任何入库文件不得出现真实值。

## 本地启动

进入对应站点的 scripts 目录（如 `nanjing/scripts/`）：

| 方式 | 操作 |
| --- | --- |
| Windows 双击 | `start.bat` 启动（自动打开后台）/ `stop.bat` 停止 / `status.bat` 查看状态 |
| 命令行 | `python start.py`（启动并打开浏览器）/ `--no-open` 不开浏览器 / `status` / `stop` |
| 直接运行 | `python run.py`（前台阻塞，Ctrl+C 停止） |

其余站点同理：`cd hefei/scripts`、`cd xuzhou/scripts`、`cd wuxi/scripts`、`cd hangzhou/scripts`。

启动脚本特性：端口占用预检（避免重复启动）、健康检查等待就绪、依赖自动检查安装
（自动探测 pypi / 清华 / 阿里 / 中科大镜像选最快）、本站独立日志 `storage/logs/run.log`、PID 记录用于可靠停止。

## 单站独立部署

站点目录完全自包含：把 `nanjing/`（或任意一站）拷贝到任意机器/目录：

1. `cd nanjing/scripts && python start.py` —— 首次运行自动在本站目录创建 `.venv` 并安装依赖
   （fastapi、uvicorn、jinja2、sqlalchemy 等，自动选最快镜像源）；
2. 首次启动自动生成 `.env` 密钥与后台初始密码（控制台打印一次）；
3. 自动建库并写入种子数据（`storage/seed.json`），前台后台即可用。

无需依赖仓库根目录的任何文件；`venv/` 只是服务器 K3s 部署的共享依赖目录，本地单站运行用不到。

## 服务器部署（K3s 容器化）

生产环境运行在服务器上的**极简 K3s**（v1.28.5+k3s1，已禁用 traefik / metrics-server /
servicelb / local-storage，系统 Pod 仅 CoreDNS，2 核 / 1.9G 内存跑五站 + Dashboard + webhook）。

### 架构

- 五站各自独立 Deployment（namespace `pysite`），`hostNetwork: true` 直接占用 8101-8105，
  宿主机 nginx 反代配置零改动；
- **共用一个镜像** `python:3.10-slim`（免构建）：Python 依赖从宿主机
  `/www/wwwroot/pysite/venv/lib/python3.10/site-packages` 以只读 hostPath 挂入，通过
  `PYTHONPATH` 生效；站点目录整体挂载到容器 `/app`；
- **数据卷**：各站 `storage/`（site.db / seed.json / uploads / cache / logs / sessions / temp / pycache）
  在站点目录内随 hostPath 持久化，**部署 / 重启 / 滚动更新永不覆盖**；
- 代码目录：服务器 `/www/wwwroot/pysite/`（Git 仓库根）；kubeconfig `/etc/rancher/k3s/k3s.yaml`。

### Git 推送自动部署（已生效）

- 仓库：`git@gitee.com:donghaichen/py-site.git`（分支 `main`，服务器部署公钥只读 pull，无法 push；
  推送在开发机执行，走 HTTPS 凭据）；
- **触发链路**：`git push` → Gitee WebHook → 服务器 K3s 内 `webhook-receiver` Pod（端口 8300，
  纯标准库、limits 64Mi）→ nsenter 进宿主机执行 `/root/k3s-deploy.sh`；
- **WebHook 地址**（Gitee 仓库 → 管理 → WebHooks，Push 事件）：
  `http://<服务器IP>:8300/hook?token=<WebHook Token>`
- 部署脚本在仓库外 `/root/k3s-deploy.sh`（不会被 `git reset` 覆盖；源码备份在仓库 `k8s/k3s-deploy.sh`），流程：
  1. `git fetch + reset --hard` 更新代码（`storage/` 被 gitignore，不受影响）；
  2. **数据卷校验**：五站 site.db 存在、体积不缩小、article 记录数不减少，异常立即中止；
  3. `kubectl rollout restart` 五站 Deployment（滚动重启）；
  4. 健康检查：五站 HTTP 200，失败自动 `rollout undo` 回滚。
- **git push 即部署，无需人工确认**；部署日志 `scripts/k3s-deploy.log`（webhook 日志 `scripts/webhook.log`）。

### K3s 管理界面（Dashboard）

- 入口：`http://<服务器IP>:10000/`（nginx 反代 + Basic Auth 双重保护，反代配置
  `/www/server/panel/vhost/nginx/k8s-dashboard.conf`，NodePort 30100 → 对外 10000）；
- 第一层 Basic Auth：`k8sadmin` / `<SSH密码>`；第二层 Dashboard Token：服务器 `/root/dashboard-token.txt`（有效期 1 年）；
- 可视化管理 Pod / Deployment / 日志 / 重启 / 回滚；因禁用 metrics-server 无 CPU/内存曲线；
- 部署清单在仓库 `k8s/`（namespace / 五站 Deployment / Dashboard / webhook / 部署脚本源），自包含可随时
  `kubectl apply -f k8s/` 重建，详见 `k8s/README.md`。

### 日常维护命令（SSH 执行）

```bash
kubectl get pods -A                                      # 全部 Pod 状态
kubectl -n pysite get pod -o wide                        # 五站 Pod
kubectl -n pysite logs deploy/pysite-nanjing --tail=50   # 某站日志
kubectl -n pysite rollout restart deploy/pysite-nanjing  # 重启某站
kubectl -n pysite rollout restart deploy                 # 重启五站
kubectl -n pysite rollout undo deploy/pysite-nanjing     # 回滚某站上次变更
tail -f /www/wwwroot/pysite/scripts/k3s-deploy.log       # 部署日志
```

站点运行日志在容器内 `storage/logs/site.log`，即宿主机 `/www/wwwroot/pysite/<站点>/storage/logs/site.log`。

### 访问方式与备份

- 只启用 HTTP(80)，未开 SSL；必须用域名 `http://...` 访问，IP 访问会落到 nginx 默认站点（正常现象）；
- K3s 自身：API Server 6443（仅本机管理）、Dashboard NodePort 30100（经反代 10000 对外）；
- **备份**：五站 `storage/` 目录与各站 `.env` 是全部状态；完整备份（storage + .env + nginx 配置）
  存放在服务器 `/root/pysite-backup-<时间戳>/`，最新备份路径记录在 `/root/.pysite-latest-backup`；
- 单站回滚：`kubectl -n pysite rollout undo deploy/pysite-<站点名>`。

## 目录结构

```
py-site/
├── k8s/                      # K3s 部署清单：namespace / 五站 Deployment / Dashboard / webhook / 部署脚本源
├── scripts/                  # 项目级脚本：nginx 反代配置源、部署日志
├── venv/                     # Python 虚拟环境（服务器 K3s 共享依赖，本地单站运行不需要）
├── README.md                 # 本文档（项目总览 + 部署总说明）
├── nanjing/                  # 完全独立的站点（可直接整体拷走部署，内含独立 README.md）
│   ├── src/app/              # 配置 / 数据库 / 模型 / 缓存 / 安全 / 应用工厂 / 各业务模块
│   ├── admin/                # 管理后台静态前端（随代码发版，FastAPI 托管）
│   ├── themes/               # 主题模板 / 静态资源 / 组件宏
│   ├── scripts/              # 站点脚本：run.py / start.py / *.bat / reset_admin / migrate / seed
│   ├── site.json             # 站点配置（公司信息 / 主题 / 端口 / 导航 / 轮播）
│   ├── .env                  # 密钥（不入库，首次启动自动生成）
│   ├── .env.example          # 端口等基础配置（start.py 读取）
│   └── storage/              # 唯一持久化目录：SQLite / 上传 / 缓存 / 日志 / 会话 / 临时（容器只挂此卷）
├── hefei/ xuzhou/ wuxi/ hangzhou/  # 各自同样结构，完全独立
```

**storage/ 是唯一持久化目录**：数据库、上传、缓存、日志、会话、临时文件全在里面；
Git 只提交 `seed.json` 和目录骨架，其余全忽略——生产数据永远不会被部署覆盖。
旧目录 `runtime/ var/ uploads/ data/` 已淘汰；代码启动时 `_migrate_legacy` 会把旧目录数据
自动迁入 `storage/`（copy 不删，兼容老部署升级）。

**admin/ 为什么在站点目录而不是 storage/**：admin 是随代码发版的管理后台静态前端（FastAPI 托管、
Git 版本管理、部署时随代码更新）；storage 是部署永不触碰的数据卷（gitignore）。如果把 admin 放进
storage，后台前端将不进 Git、部署也无法更新界面、整体拷贝站点会缺文件。

## 关键设计

- **完全独立**：每个站点代码拷到任意目录都能独立运行，五站代码互不干扰、不共享；
- **数据隔离**：各自 FastAPI 实例、SQLite、文件缓存、上传目录、主题，配置只读本站 `site.json`；
- **后台一致但各自持有**：每站内置一份相同的管理后台静态资源和 API 代码，界面一致、数据独立；
- **CRUD 配置驱动**：后台所有列表复用 `crud.js`，后端返回配置 JSON 驱动渲染，无需逐业务写页面；
- **SQLite + 文件缓存**：零外部依赖，开箱即用；
- **缓存失效**：后台增删改、切主题、改配置后自动清空站点页面缓存，前台立即生效
  （整页缓存在 `storage/cache/pages/`，后台与搜索页、在线留言不缓存）；
- **前台列表排序**：新闻 / 案例 / 产品按后台选择的发布时间倒序（置顶优先，无发布时间回落创建时间），
  后台列表排序与前台一致；未到发布时间的内容前台不显示（定时发布）；
- **前台时间显示**：永远显示发布时间（publish_at），无发布时间回落创建时间。

## 富文本与表单能力

- **wangEditor 富文本**：正文用本地 wangEditor v5（图片上传走 `/api/admin/upload`），前台 HTML 安全渲染；
- **拖拽上传**：封面等图片字段为拖拽/点击上传组件，实时预览、可移除；所有文件/图片/附件表单统一使用
  `admin/js/upload.js` 上传组件（缩略图预览列表 + 素材库选择弹窗 + 图片大图预览 + 头像方形裁剪器）；
- **表单模型可视化编辑**：自定义表单字段一行一个可视化编辑，无需手写 JSON；
- **表单校验**：JustValidate 前端校验，必填字段红色 `*`，提交失败提示具体字段；
- **内容表单精简**：作者自动取当前登录用户、发布时间自动填当前、摘要从正文自动生成；
- **访问别名**：不填时自动按标题拼音或英文生成；
- **产品/案例图集**：多图上传，存 extra JSON；
- **上传目录模板**：`{filetype}/{year}{month}/{day}`，可用变量 `{filetype} {year} {month} {day}
  {datetime} {timestamp} {rand6} {rand8}`，文件名为内容 md5 + 后缀（`src/app/core/services.py::render_save_dir`）；
- **页脚**：备案号链接 `https://beian.miit.gov.cn`，公网安备案号链接 `https://beian.mps.gov.cn/`。

## 管理后台 UI/UX

- **品牌**：企业管理系统 V35.26.1351；双主题（右上角 深色/浅色 切换，localStorage 记忆，全站变量化配色）；
- **G2 图表**：仪表盘内容发布趋势（面积图）、内容模型分布（环形图），主题切换自动重绘；
- **菜单开关**：「系统设置 → 系统开关」一键隐藏站群/会员/订单/评论/开发/多语言/短信/AI 等菜单组；
- **基础设置**：QQ、微信二维码、ICP 备案号、公网安备案号、统计代码、联系人等；
- **交互**：删除/恢复/导出/退出用带类型图标的确认弹窗；新增/编辑在弹窗内完成（点空白处/ESC 不关闭）；
  全局 Loading、骨架屏、数字滚动、进场动效；主色按钮文字图标统一白色；
- **H5 自适应**：手机端侧栏抽屉、统计卡两列、图表表格自适应；
- **插件中心**：OSS / COS 云存储插件安装/卸载/启用/配置，「上传设置」可切换上传驱动与水印九宫格位置；
- **主题管理**：卡片/列表双视图，五套主题一键启用。

## 后台功能（12 个一级模块 · 43 个菜单项，全部可用）

| 一级模块 | 二级菜单 |
| --- | --- |
| 仪表盘 | 数据概览、内容模型分布、最近内容、待办统计 |
| 站群管理 | 站点列表、地区库、批量生成、站群同步、站群设置 |
| 内容管理 | 栏目分类、标签管理、文章、产品、案例、内容回收站 |
| 素材库 | 文件列表（图片/视频/附件）、批量上传 |
| 会员管理 | 会员列表、会员分组、会员等级、余额流水、积分流水 |
| 订单与支付 | 订单列表、退款记录、支付配置 |
| 自定义表单 | 表单模型、提交记录 |
| 评论管理 | 评论列表（待审核/通过/驳回） |
| 运维工具 | 定时任务、任务日志、备份恢复、SEO 配置（网站地图为系统功能，实时动态生成） |
| 权限管理 | 管理员列表、角色管理、权限节点 |
| 系统设置 | 基础设置、多语言管理、语言包管理、上传设置、短信设置、AI 配置、安全设置、操作日志 |
| 开发管理 | CRUD 管理、内容模型、主题管理、插件管理、开放 API |

左侧菜单 + 顶部导航 + 多 Tab + 弹窗表单 + 侧边筛选 + 批量操作 + 导入导出 + 回收站/恢复；
菜单由后端 `/api/admin/menu` 动态驱动，超级管理员全可见。

## 数据模型（41 张表）

系统后台（管理员/角色/权限/审计/配置/素材/定时任务/任务日志/备份）、站群（站点/地区/站点变量/同步记录/
地区映射）、多语言（语言/语言包）、内容（内容类型/栏目/标签/内容/多语言子表/扩展字段/标签关联）、
会员（分组/等级/会员/地址/收藏/足迹/余额流水/积分流水）、表单（模型/记录）、订单库存（SKU/订单/订单项/
退款/库存日志）、评论、留言、设置。

每站一份独立 SQLite，表结构完全相同；软删除表支持回收站/恢复/彻底删除。

## 数据入库

五家公司资料中的图片、PDF、Word 等文件已全部扫描登记到各自站点的**素材表（media）**
（nanjing 4 / hefei 32 / xuzhou 15 / wuxi 2 / hangzhou 17），栏目、内容、表单、公司信息写入对应数据表。
后台「素材库」可直接管理；前台 Hero/推荐/案例使用各站真实图片与背景。

## API

- `/api/admin/*` 后台管理接口（登录鉴权，含通用 CRUD、备份、Sitemap 等）
- `/api/frontend/*` 前台公共接口（留言、表单、搜索）
- `/api/health` 健康检查
- `/sitemap.xml` 站点地图（系统内置，按固定页面 + 已启用栏目 + 已发布内容实时生成，不落地静态文件；
  后台「运维工具 → SEO 配置」只读查看）

## 主题风格（五套完全不同）

1. 南京 · 深蓝商务 + 金色点缀 + 建筑剪影 Banner
2. 合肥 · 橙色活力 + 圆角卡片 + 波浪装饰
3. 徐州 · 红色政务 + 对称庄重 + 金线装饰
4. 无锡 · 墨绿高端 + 杂志排版 + 衬线字体
5. 杭州 · 黑白极简 + 科技网格 + 几何 Logo

每套主题仅由 `base.html` / `index.html` / `style.css` 三个文件构成，页面逻辑全部复用公共模板与组件宏。
uploads 与 theme-libs 由 nginx 直出（sendfile 零拷贝），应用侧保留同名路由作本地开发兜底；
反代配置见 `scripts/nginx/*.conf`。
