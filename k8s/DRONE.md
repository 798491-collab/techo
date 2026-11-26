# Drone CI —— 手动「Build Now」界面

给这台低配服务器加一个 Jenkins 风格的构建按钮，**不动现有部署链路**。

## 它是什么

```
你在 Drone 网页点 "Run pipeline"
        ↓
exec runner（宿主机二进制）执行 .drone.yml
        ↓
curl http://127.0.0.1:8300/hook?token=...   ← 复用现成的 webhook 接收器
        ↓
nsenter → k8s/k3s-deploy.sh（拉代码/滚动更新/健康检查/失败回滚）
```

- **Server**：`drone/drone:2` 跑在现有 K3s，内置 SQLite（hostPath `k8s/drone-data/`），limits 128Mi。
- **Runner**：官方 `drone-runner-exec` 二进制，systemd 托管，直接在宿主机执行命令——无需 Docker（你只有 containerd），常驻内存可忽略。
- **零侵入**：`git push` 的自动部署照旧；Drone 只是并列的第二个入口。

> ⚠️ exec runner 官方已归档（功能稳定但不再更新）。它不适合跑不可信代码，本项目只执行自己仓库的部署脚本，属于官方推荐的「需要主机访问的子集」场景，安全边界吻合。若日后要跑第三方 PR，再换 Docker runner。

## 一次性配置（约 10 分钟）

### 1. Gitee 建 OAuth 应用

Gitee → 设置 → 第三方应用 → 创建应用：

| 字段 | 值 |
|---|---|
| 应用主页 | `http://<你的CI域名>` |
| 回调地址 | `http://<你的CI域名>/login` |

记下 **Client ID** 和 **Client Secret**。

### 2. nginx 反代

```bash
cp scripts/nginx/drone.conf.example scripts/nginx/<你的CI域名>.conf
# 改 server_name 与日志路径 → 域名解析到本机 → 重载 nginx
```

### 3. 一键安装

在服务器上：

```bash
cd /www/wwwroot/pysite
sudo bash k8s/install-drone.sh
```

脚本会依次问你：CI 对外地址（如 `ci.example.com`）、Client ID、Client Secret、Gitee 用户名。
然后自动完成：创建 Secret → 部署 server → 下载安装 runner → 启动 → 等待就绪。

### 4. 首次使用

1. 浏览器打开 `http://<你的CI域名>`，用 Gitee 账号登录；
2. Repos 页找到 `techo.git`，点 **Activate**；
3. Builds 页点 **Run pipeline**，分支选 `main` → **Run**；
4. 实时日志里能看到「已提交到部署队列」和部署结果，等价于 Jenkins 的 Build Now。

## 验证与排障

```bash
kubectl -n pysite get pod -l app=drone-server          # server 状态
kubectl -n pysite logs -l app=drone-server -f          # server 日志
tail -f /var/log/drone-runner-exec/log.txt             # runner 日志（连接/接单）
tail -f /www/wwwroot/pysite/scripts/k3s-deploy.log     # 真正的部署日志
curl -fsS http://127.0.0.1:30080/healthz               # 健康检查
```

| 现象 | 原因 / 处理 |
|---|---|
| 登录跳回 Gitee 报 redirect_uri 不符 | OAuth 回调地址与 `DRONE_SERVER_HOST` 必须完全一致（含 http/端口） |
| Builds 页显示 `no runners available` | runner 没连上：`tail /var/log/drone-runner-exec/log.txt`，核对 `DRONE_RPC_SECRET` 与 server Secret 一致 |
| 点运行后日志卡在「已提交队列」 | 检查 `tail -f scripts/k3s-deploy.log`，多半是 webhook token 文件或 8300 接收器问题 |
| Gitee 仓库列表为空 | OAuth 应用权限不足，或该仓库不属于登录账号 |

## 与 Gitee Go 的关系

`.workflow/ci.yml`（Gitee Go 流水线）与本方案都能提供手动按钮，**二选一即可**：

- **Drone（本方案）**：开源、自建、不依赖云端额度，代码和状态都在自己服务器；
- **Gitee Go**：纯云端零运维，但闭源、依赖云端额度与主机组 agent。

两者并存也不冲突——都只是往同一个 webhook 发触发。
