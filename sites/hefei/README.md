# 合肥筑骋建筑工程咨询有限公司 · 官网

本目录是**完全独立、自包含**的站点系统：自带全套后端代码（FastAPI）、管理后台前端、主题模板、
启动脚本与数据目录，**不依赖本目录之外的任何共享代码**——把整个目录拷贝到任意机器/任意路径
都能直接独立部署运行。仓库内其余站点（nanjing / hefei / xuzhou / wuxi / hangzhou）与本站结构
完全相同、代码互不共享、数据完全隔离。

## 站点信息

| 项目 | 值 |
| --- | --- |
| 公司 | 合肥筑骋建筑工程咨询有限公司 |
| 端口 | 8102 |
| 域名 | `<域名>`（敏感信息不入库，以服务器 nginx 反代配置与本站 site.json 为准） |
| 前台 | http://127.0.0.1:8102/ |
| 后台 | http://127.0.0.1:8102/admin/（建议带结尾斜杠，`/admin` 会 307 跳转） |
| 主题 | 橙色活力 · 圆角卡片 · 波浪装饰（橙色活力 · 卡片式） |
| 后台账号 | `admin`（初始密码见下文「密钥与后台密码」） |

## 快速启动

### Windows 双击（最简单）
进入 `scripts/` 目录双击：

| 脚本 | 作用 |
| --- | --- |
| `start.bat` | 启动本站点，自动打开后台，按 Ctrl+C 停止 |
| `stop.bat` | 停止本站点 |
| `status.bat` | 查看本站点运行状态 |

### 命令行
```bash
cd scripts
python start.py                  # 启动（自动创建 .venv、安装依赖、打开浏览器）
python start.py --no-open        # 启动但不打开浏览器
python start.py status           # 查看运行状态
python start.py stop             # 停止
python run.py                    # 直接运行入口（前台阻塞，Ctrl+C 停止）
```

启动脚本特性：端口占用预检（避免重复启动）、健康检查等待就绪、依赖自动检查安装
（自动探测 pypi / 清华 / 阿里 / 中科大镜像选最快）、独立日志 `storage/logs/run.log`、
PID 记录（`.pid`）用于可靠停止。

### 独立部署三步（拷走即用）

1. 把本目录整体拷贝到目标机器任意位置；
2. `cd scripts && python start.py` —— 首次运行自动在本目录创建 `.venv` 并安装依赖
   （fastapi、uvicorn、jinja2、sqlalchemy、pillow 等）；
3. 首次启动自动生成 `.env` 密钥与后台初始密码（控制台打印一次，请立即保存），
   自动建库并写入种子数据，前台后台即可用。

仓库根目录的 `venv/` 只是服务器 K3s 容器部署用的共享依赖目录，本地单站运行完全用不到。

## 密钥与后台密码

- `.env`（不入 Git）保存 `SECRET_KEY` 与 `ADMIN_PASSWORD`；不存在时启动自动生成
  （SECRET_KEY 64 位十六进制，ADMIN_PASSWORD 24 位随机串），控制台打印一次初始密码；
- 生成后落盘固定、重启不变；已有值绝不覆盖；环境变量 `PYSITE_SECRET` / `PYSITE_ADMIN_PASSWORD` 优先；
- 首次建库后密码固化于数据库（存 hash），改密在后台「个人资料」；也可用
  `scripts/reset_admin.py` / `scripts/reset_password.py` 重置；
- ⚠️ 删除 `.env` 后重启会重新生成新密钥，旧登录态与旧后台密码全部失效。

## 目录结构

```
<本目录>/
├── src/app/           # 全部后端代码：core（配置/数据库/安全/缓存）、content（内容）、
│                      # media（素材）、pages（前台渲染）、forms（表单）、api 路由
├── admin/             # 管理后台静态前端（随代码发版，FastAPI 托管；不放在 storage/ 的原因：
│                      #   storage 是部署永不触碰的数据卷，admin 必须进 Git 随部署更新）
├── themes/            # 主题模板（base.html / index.html / style.css）与静态资源、组件宏
├── scripts/           # run.py / start.py / *.bat / reset_admin.py / seed.py / migrate_*.py
├── site.json          # 站点配置（公司信息 / 主题 / 端口 / 导航 / 轮播）
├── .env.example       # 端口等基础配置（start.py 读取）
├── .env               # 密钥（不入库，首次启动自动生成）
├── pyproject.toml     # Python 项目定义
├── migrations/        # 数据库迁移脚本
├── tests/             # 冒烟测试（需先启动服务，或设置 BASE_URL）
└── storage/           # ★ 唯一持久化目录（数据卷，除 seed.json 外不入 Git）
    ├── site.db        #   SQLite 数据库（41 张表，软删除支持回收站）
    ├── seed.json      #   种子数据（入库 Git）
    ├── uploads/       #   上传文件（32 份公司资料已登记素材表）
    ├── cache/         #   文件缓存（pages/ 为前台整页 HTML 缓存）
    ├── logs/          #   run.log / site.log 运行日志
    ├── sessions/      #   会话
    └── temp/          #   临时文件
```

**storage/ 是唯一持久化目录**：数据库、上传、缓存、日志、会话全在里面；Git 只提交 `seed.json`
与目录骨架，其余全忽略——生产数据永远不会被部署覆盖。旧目录 `runtime/ var/ uploads/ data/` 已淘汰，
启动时 `_migrate_legacy` 自动把旧目录数据迁入 `storage/`（copy 不删，兼容老部署升级）。

## 功能与后台

- 管理后台 12 个一级模块 / 43 个菜单项全部可用（仪表盘、内容管理、素材库、表单、评论、
  运维工具、权限、系统设置、开发管理等），菜单由 `/api/admin/menu` 动态驱动；
- 双主题（深色/浅色）切换记忆、G2 仪表盘图表、wangEditor 富文本、统一拖拽上传组件 +
  素材库选择 + 头像裁剪、插件中心（OSS/COS）、主题一键切换、确认弹窗、骨架屏与动效、H5 自适应；
- **内容排序**：前台新闻/案例/产品按后台选择的发布时间倒序（置顶优先，无发布时间回落创建时间），
  后台列表排序与前台一致；未到发布时间的内容前台不显示（定时发布）；
- 内容表单：发布时间自动填当前、摘要从正文生成、访问别名自动按拼音/英文生成、产品/案例图集。

## 网站地图（sitemap）

- `sitemap.xml` 是系统内置功能，无需后台维护数据：按「固定页面 + 已启用栏目 + 已发布内容」
  实时动态生成，支持 `priority`/`changefreq`/`lastmod`，不落地任何静态文件；
- 后台「运维工具 → SEO 配置」提供只读查看入口。

## 静态资源与性能

- 整页 HTML 缓写在 `storage/cache/pages/`；后台与搜索页、在线留言不缓存；
- **后台任何数据增删改、切换主题、修改配置都会自动清空页面缓存**，改完立即生效；
- 浏览量等实时数据用 `<span data-view-count>` 占位，JS 调 `/api/stats/{id}` 异步渲染；
- uploads 与 theme-libs 生产环境由 nginx 直出（sendfile 零拷贝），应用侧保留同名路由作
  本地开发兜底；上传目录模板 `{filetype}/{year}{month}/{day}`（后台「上传设置」可改）。

## API

| 接口 | 说明 |
| --- | --- |
| `/api/admin/*` | 后台管理（登录鉴权，通用 CRUD、上传、备份等） |
| `/api/frontend/*` | 前台公共（留言、表单提交、搜索） |
| `/api/health` | 健康检查 |
| `/sitemap.xml` | 站点地图 |

## 测试

```bash
python tests/test_smoke.py      # 需先启动服务；或设置 BASE_URL 指向运行中的站点
```

## 生产部署（K3s，本站已部署）

- 独立 Deployment：`pysite/hefei`（namespace `pysite`），hostNetwork 占用端口 8102，
  站点目录整体挂载容器 `/app`，`storage/` 随 hostPath 持久化、部署永不覆盖；
- **git push 即自动部署**：Gitee WebHook → 服务器 webhook-receiver（8300）→ 仓库内 `k8s/k3s-deploy.sh`（先复制到 /tmp 再执行，避免 git reset 覆盖自身）
  → 数据卷校验 → 滚动重启 → HTTP 健康检查 → 失败自动回滚；
- 常用运维（SSH 到服务器）：
  ```bash
  kubectl -n pysite logs deploy/pysite-hefei --tail=50      # 本站日志
  kubectl -n pysite rollout restart deploy/pysite-hefei     # 重启本站
  kubectl -n pysite rollout undo deploy/pysite-hefei        # 回滚本站
  ```
- 完整部署说明见仓库根 `README.md` 与 `k8s/README.md`。
