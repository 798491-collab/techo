# 无锡君鑫建筑工程咨询有限公司 · 官网

> 本目录是**完全独立、自包含**的站点系统：自带全套后端代码（FastAPI）、管理后台前端、主题模板、
> 启动脚本与数据目录，把整个目录拷贝到任意机器/任意路径都能直接运行。
> **通用说明不在本文档重复**（与根文档保持融合、同步维护）：快速启动、后台账号与密钥、
> 目录结构与持久化、API、测试、部署架构与运维排障，统一见
> 仓库根 [`README.md`](../../README.md)、[`k8s/README.md`](../../k8s/README.md)、[`k8s/DRONE.md`](../../k8s/DRONE.md)。

## 站点信息

| 项目 | 值 |
| --- | --- |
| 公司 | 无锡君鑫建筑工程咨询有限公司 |
| 域名 | `https://www.wuxijunxin.com/`（服务器 nginx 反代，配置见仓库 `scripts/nginx/`） |
| 端口 | 8104（ClusterIP `10.43.100.104`） |
| 前台 | http://127.0.0.1:8104/ |
| 后台 | http://127.0.0.1:8104/admin/（建议带结尾斜杠） |
| 线上后台 | https://www.wuxijunxin.com/admin/ |
| 主题 | 墨绿高端 · 杂志排版 · 衬线字体 |
| 后台账号 | `admin`（初始密码首次启动自动生成并打印一次，详见根 README「后台账号与密钥」） |

## 本站要点

- 站点配置（公司信息 / 轮播 / 导航等）**全部存数据库**，后台「系统配置」在线修改，改完自动清整页缓存；
  密钥只放本站 `.env`（首次启动自动生成，不入 Git）。
- `storage/` 是唯一持久化目录：`site.db`（SQLite）、`uploads/`、`cache/`（含 pages/ 整页缓存）、
  `logs/`、`sessions/`、`temp/`、`seed.json`（种子数据，入库 Git）；部署永不覆盖。
- 主题静态资源在 `themes/static/`，经 `/theme-assets/` 提供，`?v=static_ver` 控制缓存；
  首页专属脚本（轮播/页签）抽离在 `themes/static/js/home.js`，不再内联在模板里。
- 本地启动：`cd scripts && python start.py`（Windows 双击 `start.bat`），详见根 README「快速启动」。

## 生产部署（K3s，本站已上线）

- 独立 Deployment `pysite/wuxi`（namespace `pysite`）+ 固定 ClusterIP Service（无 hostNetwork/hostPort）；
  更新策略 RollingUpdate（`maxUnavailable: 0`），发版全程无 502。
- **git push 即自动部署**：Gitee WebHook → Drone CI 校验（`http://45.91.139.246:30080`）→ 自动 promote
  production → 生产构建部署：服务器 webhook 接收器（8300）→ `k8s/k3s-deploy.sh`
  （apply YAML 真相源 → 注入 commit 注记 → 同步 nginx 反代并 reload → ClusterIP 健康检查 → 失败自动回滚）。
  生产部署/回滚记录见 Drone 仓库 **Deployments** 页。
- 常用运维（SSH 到服务器）：

  ```bash
  kubectl -n pysite logs deploy/pysite-wuxi --tail=50      # 本站日志
  kubectl -n pysite rollout restart deploy/pysite-wuxi     # 重启本站（无 502）
  kubectl -n pysite rollout undo deploy/pysite-wuxi        # 回滚本站
  ```

- 架构 / 端口表 / 502 排查实录 / Drone 配置与故障处理，见根 `README.md` 与 `k8s/README.md`、`k8s/DRONE.md`。
