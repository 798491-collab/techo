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

- Dashboard Token：缺失时随机生成 → `k8s/secrets/dashboard-token.txt`（有效期 1 年）
- WebHook Token：缺失时随机生成 → `k8s/secrets/webhook-token.txt`，并自动写入 webhook-receiver
- 统一存放在本目录 `secrets/`（.gitignore 已忽略），不写 `/root`、`/www/server` 等系统目录
- 重新生成：删除 secrets/ 下对应文件后重跑脚本（或下次部署自动补齐）

## 管理界面

- Kubernetes Dashboard：NodePort 30100
- 外部访问：`http://<服务器IP>:10000/`（nginx 反代，无 Basic Auth）
- 登录即 Dashboard 自带界面：粘贴 Token（服务器 `k8s/secrets/dashboard-token.txt`）
- 手动更新 token：`kubectl -n kubernetes-dashboard create token admin-user --duration=8760h`
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
3. `kubectl rollout restart` 五站 Deployment（hostPath 代码更新后重启即生效）
4. 等待就绪 + 五站 HTTP 200 健康检查
5. 任一失败 → 自动回滚代码 + 重启

**脚本在 `/root/`（仓库外），不会被 git pull 覆盖。** 仓库内的 `k8s-deploy.sh` 是源备份。

## 常用命令

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl -n pysite get pod -o wide          # 五站状态
kubectl -n pysite logs -l app=pysite-hangzhou --tail=50
kubectl -n pysite rollout restart deployment/pysite-hangzhou
kubectl get pods -A                        # 全部 Pod
systemctl status k3s                       # K3s 本身
```

## 数据备份

定期备份五站 `storage/` 目录与各站 `.env`（这是全部运行状态）；完整备份（storage + .env +
nginx 配置）存放在服务器 `/root/pysite-backup-<时间戳>/`，最新备份路径记录在 `/root/.pysite-latest-backup`。
