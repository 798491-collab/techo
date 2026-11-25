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

| 站点 | 端口 |
|---|---|
| nanjing | 8101 |
| hefei | 8102 |
| xuzhou | 8103 |
| wuxi | 8104 |
| hangzhou | 8105 |

> 域名属敏感信息不入库，以服务器 nginx 反代配置与各站 `site.json` 为准。

Pod 用 `hostNetwork: true` 直接占用上述端口，nginx 反代配置无需改动。

## 凭据（自动生成，无需人工设置）

`k8s/provision-secrets.sh`（幂等，部署脚本每次部署都会自动调用）：

- WebHook Token：缺失时随机生成 → `k8s/secrets/webhook-token.txt`，并自动写入 webhook-receiver
- KubePi 管理员密码：部署时随机生成并通过 KubePi API 改掉默认 `admin/kubepi`
  → `k8s/secrets/kubepi-admin.txt`（若 API 改密未成功，首次登录系统强制要求改密，双保险）
- 五站后台管理员密码：缺失时随机生成写入 `sites/<站>/.env`（与应用内首启生成规则一致，
  账号均为 `admin`；已有密码不会被覆盖）
- **全部凭据统一登记** → `k8s/secrets/credentials.txt`（每次部署刷新，权限 600，类似
  MySQL 安装后的初始密码文件）
- 凭据文件存放在本目录 `secrets/`（.gitignore 已忽略），不写 `/root`、`/www/server` 等系统目录
- 重新生成某凭据：删除 secrets/ 下对应文件后重跑脚本（或下次部署自动补齐）

## 管理界面（KubePi，中文）

- **KubePi**：现代化中文 K8s 面板（1Panel 团队出品），NodePort 30110
- 外部访问：`http://<服务器IP>:10000/`（nginx 反代，含 WebSocket 支持）
- 登录：账号 `admin` + 随机密码（部署时自动生成并改掉默认值，见 `k8s/secrets/credentials.txt`；
  若改密未成功则默认 `admin/kubepi`，首次登录系统强制要求改密）
- 首次使用需导入集群：「集群管理 → 添加集群」→ 认证方式 Token：
  - API 地址 `https://<服务器IP>:6443`；Token 用服务器 `k8s/secrets/kubepi-cluster-token.txt`
    （kubepi-user SA，cluster-admin，有效期 10 年）；跳过 TLS 校验（自签证书）
- 数据持久化：宿主机 `/www/wwwroot/pysite/kubepi-data/`；重建：`kubectl apply -f k8s/kubepi.yaml`
- 集群导入 Token：`k8s/secrets/kubepi-cluster-token.txt`（kubepi-user SA，cluster-admin，有效期 10 年；
  重新生成：`kubectl -n kube-system create token kubepi-user --duration=87600h`）
- 接收器健康检查：`http://<服务器IP>:8300/healthz`（200 = 自动部署链路正常）
- 全部运维入口汇总见仓库根 `README.md` 的「运维入口速查」

## 自动部署（K3s 自建 webhook 接收器）

仓库 `main` 分支 push → Gitee WebHook → **K3s 内 webhook 接收器**（`pysite/webhook-receiver`，
端口 8300）→ nsenter 进宿主机执行 `/root/k3s-deploy.sh`：

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
3. 发版：把 commit、提交说明、发版时间写入五站 Deployment 的 Pod 模板注记（触发一次滚动
   更新 = 一个新修订版本，代码经 hostPath 挂载，重启即生效）
4. 等待就绪 + 五站 HTTP 200 健康检查
5. 任一失败 → 自动回滚（代码 reset + `kubectl rollout undo` 回退修订版本）

## 发版与部署记录

每次 git push 发版后，可以从以下几处查到记录：

| 记录 | 位置 | 内容 |
|------|------|------|
| 发版清单 | 服务器 `scripts/release-history.txt` | 每次成功发版一行：时间 + commit + 提交说明 + 作者；失败/回滚也记录 |
| 部署过程 | 服务器 `scripts/k3s-deploy.log` | 每次部署的完整过程（拉取版本、健康检查、回滚原因等） |
| 修订历史 | KubePi → 工作负载 → 部署 → 详情 → 「修订历史」 | 每个修订版本的 Pod 注记里有 `pysite/commit`、`pysite/commit-subject`、`pysite/deployed-at`，可对比任意两版并一键回滚 |
| 命令行 | `kubectl -n pysite rollout history deployment/pysite-<站>` | 修订版本列表 |

回滚到上一版：`kubectl -n pysite rollout undo deployment/pysite-<站>`（或直接在 KubePi 修订
历史里点回滚）。注意：代码经 hostPath 挂载，回滚 Pod 的同时需 `git reset --hard <旧 commit>`
同步代码；部署脚本的自动回滚已包含这两步。

**脚本在 `/root/`（仓库外），不会被 git pull 覆盖。** 仓库内的 `k8s-deploy.sh` 是源备份。

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
