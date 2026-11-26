# K3s 部署说明（五站独立 / 小内存优化）

## 架构

- **极简 K3s**：单节点 server，禁用 Traefik / metrics-server / servicelb / local-storage，
  仅保留 CoreDNS。K3s + containerd 约 500MB，系统 Pod 只有 1 个。
- **五站完全独立**：每站一个 Deployment（`pysite-<site>`），独立 hostPath 卷、独立端口、
  独立 Pod。任何一站重启/故障不影响其他站。
- **共用镜像**：`python:3.10-slim`（唯一镜像），依赖从宿主机 venv 的 site-packages
  以只读 hostPath 挂入（PYTHONPATH），无需为每个站构建镜像，最省磁盘。
- **代码与数据分离**：
  - 站点目录 `/www/wwwroot/pysite/sites/<site>/` 整体挂到容器 `/app`（含 src/admin/themes/.env）
  - `storage/`（db/uploads/cache/logs/sessions）在站点目录内，随 hostPath 持久化
  - **git pull 只更新跟踪文件，storage 被 .gitignore 忽略，永不覆盖**

## 端口

| 站点 | Service ClusterIP | 端口 |
|---|---|---|
| nanjing | 10.43.100.101 | 8101 |
| hefei | 10.43.100.102 | 8102 |
| xuzhou | 10.43.100.103 | 8103 |
| wuxi | 10.43.100.104 | 8104 |
| hangzhou | 10.43.100.105 | 8105 |

> 域名属敏感信息不入库，以服务器 nginx 反代配置为准；站点基础信息全部存数据库（后台「系统配置」）。

Pod 不用 `hostNetwork`/`hostPort`，改由固定 ClusterIP 的 Service 暴露；nginx 反代到 ClusterIP。
更新策略 `RollingUpdate`（`maxUnavailable: 0`）——新旧 Pod 并存、Service 平滑切流，发版全程无 502。

**真相源**：`deploy-<站>.yaml` / `service-<站>.yaml` / `scripts/nginx/*.conf` 全部由部署脚本每次 `apply`，
线上配置自动对齐仓库，杜绝「线上与 YAML 不一致」的漂移（如曾经线上有 `cpu: 500m` 而 YAML 缺失）。

## 凭据（自动生成，无需人工设置）

`k8s/provision-secrets.sh`（幂等，部署脚本每次部署都会自动调用）：

- WebHook Token：缺失时随机生成 → `k8s/secrets/webhook-token.txt`，并自动写入 webhook-receiver
- 五站后台管理员密码：缺失时随机生成写入 `sites/<站>/.env`（与应用内首启生成规则一致，
  账号均为 `admin`；已有密码不会被覆盖）
- **全部凭据统一登记** → `k8s/secrets/credentials.txt`（每次部署刷新，权限 600，类似
  MySQL 安装后的初始密码文件）
- 凭据文件存放在本目录 `secrets/`（.gitignore 已忽略），不写 `/root`、`/www/server` 等系统目录
- 重新生成某凭据：删除 secrets/ 下对应文件后重跑脚本（或下次部署自动补齐）

## 管理入口

- K8s 资源管理统一走命令行 `kubectl`（或任意 k8s 客户端连 `https://<服务器IP>:6443`）
- 接收器健康检查：`http://<服务器IP>:8300/healthz`（200 = 自动部署链路正常）
- 全部运维入口汇总见仓库根 `README.md` 的「运维入口速查」

## 自动部署（K3s 自建 webhook 接收器）

仓库 `main` 分支 push → Gitee WebHook → **K3s 内 webhook 接收器**（`pysite/webhook-receiver`，
端口 8300）→ nsenter 进宿主机，把仓库内 `k8s/k3s-deploy.sh` 复制到 `/tmp` 再执行：

> 部署脚本只有仓库 `k8s/k3s-deploy.sh` 一份，服务器 `/root` 下无需再放副本。
> 复制到 `/tmp` 执行是因为脚本内部会 `git reset --hard`，直接跑仓库里的那份会在发版时
> 把正在运行的脚本自身覆盖，导致 bash 执行错乱。

- **触发地址**（配置在 Gitee 仓库 → 管理 → WebHooks）：
  `http://<服务器IP>:8300/hook?token=<WebHook Token>`
- 接收器：纯 Python 标准库（零依赖），跑在已缓存的 `python:3.10-slim` 镜像里，limits 64Mi，
  token 校验失败返回 403；健康检查 `http://<IP>:8300/healthz`
- 接收器脚本随 Git 发版（hostPath 挂仓库 `k8s/` 目录）；WebHook token 真实值只保存在服务器本地，
  仓库内 `k8s/webhook.yaml` 为占位符——更换 token 时在服务器上填入真实值后
  `kubectl apply -f k8s/webhook.yaml && kubectl -n pysite rollout restart deploy/webhook-receiver` 生效
- 部署日志：`scripts/k3s-deploy.log`（宿主机执行）+ `scripts/webhook.log`（接收器）

部署脚本执行流程：

1. `git fetch + reset --hard`（更新代码，不碰 storage）
2. 数据卷就绪检查：五站 `sites/<站点>/storage/site.db` 存在且非空（storage 是 gitignore 的
   挂载数据卷，git 不触碰；此检查只防目录结构异常，无备份/复制开销）
3. `apply` 五站 Service（ClusterIP 固定 IP，selector 先指向旧 Pod，ClusterIP 立即可用）
4. 发版：`apply` 仓库 `deploy-<站>.yaml`（把 commit / 说明 / 时间注入 Pod 模板注记占位符），
   YAML 是唯一真相源——resources / 探针 / 更新策略全部以此为准；触发一次滚动更新 = 一个新修订版本
5. 同步 `scripts/nginx/*.conf` → 服务器 vhost 目录，`nginx -t` 通过后 reload，反代切到 ClusterIP
6. 等待就绪 + 经 ClusterIP 五站 HTTP 200 健康检查
7. 任一失败 → 自动回滚（代码 reset + `kubectl rollout undo` 回退修订版本）

> 零停机关键顺序：Service 先建 → nginx 切 ClusterIP（此时旧 Pod 仍在岗）→ 再滚动替换 Deployment。
> 若反过来先替换 Pod，nginx 仍指向旧地址会出现短暂 502。

## 发版与部署记录

每次 git push 发版后，可以从以下几处查到记录：

| 记录 | 位置 | 内容 |
|------|------|------|
| 发版清单 | 服务器 `scripts/release-history.txt` | 每次成功发版一行：时间 + commit + 提交说明 + 作者；失败/回滚也记录 |
| 部署过程 | 服务器 `scripts/k3s-deploy.log` | 每次部署的完整过程（拉取版本、健康检查、回滚原因等） |
| 修订历史 | `kubectl -n pysite rollout history deployment/pysite-<站>` | 每个修订版本的 Pod 注记里有 `pysite/commit`、`pysite/commit-subject`、`pysite/deployed-at`，可对比任意两版并回滚 |
| 命令行 | `kubectl -n pysite rollout history deployment/pysite-<站>` | 修订版本列表 |

回滚到上一版：`kubectl -n pysite rollout undo deployment/pysite-<站>`。注意：代码经 hostPath 挂载，
回滚 Pod 的同时需 `git reset --hard <旧 commit>` 同步代码；部署脚本的自动回滚已包含这两步。

**脚本只有仓库内 `k8s/k3s-deploy.sh` 一份**（`/root/` 无需副本）：调用方先复制到 `/tmp` 再执行，既不会被 git pull 覆盖自身，也不污染系统目录。

## 手动构建按钮（Drone CI，可选）

- 与 push 自动部署并列，提供一个 Jenkins 风格的 **Run pipeline** 按钮：`.drone.yml` 只调用
  同一个 webhook 接收器（8300），因此走的是上面这套已验证的部署/回滚逻辑；
- Server：`drone/drone:2` 跑在 K3s（SQLite hostPath `k8s/drone-data/`，limits 128Mi）；
  Runner：`drone-runner-exec` 二进制跑在宿主机（无需 Docker），常驻内存可忽略；
- 安装、Gitee OAuth 与排障的完整步骤见 **`k8s/DRONE.md`**。

## 常用命令

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl -n pysite get pod -o wide          # 五站状态
kubectl -n pysite logs -l app=pysite-hangzhou --tail=50
kubectl -n pysite rollout restart deployment/pysite-hangzhou
kubectl -n pysite rollout history deployment/pysite-hangzhou   # 发版修订历史
kubectl -n pysite rollout undo deployment/pysite-hangzhou      # 回滚到上一修订版
kubectl get pods -A                        # 全部 Pod
systemctl status k3s                       # K3s 本身
```

## 数据备份

定期备份五站 `storage/` 目录与各站 `.env`（这是全部运行状态）；完整备份（storage + .env +
nginx 配置）存放在服务器 `/root/pysite-backup-<时间戳>/`，最新备份路径记录在 `/root/.pysite-latest-backup`。
