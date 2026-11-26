# Drone CI —— 唯一的部署入口（手动 Build Now + push 自动触发）

给这台低配服务器加一个 Jenkins 风格的构建按钮，并让 `git push` 的自动部署也统一收口到 Drone。

## 它是什么

```
入口 A：你在 Drone 网页点 "Run pipeline"       入口 B：git push
            ↓                                        ↓
            └──────────→ Drone :30080/hook ←──────────┘
                              ↓
                    exec runner（宿主机二进制）执行 .drone.yml
                              ↓
                    curl http://127.0.0.1:8300/hook?token=...   ← 8300 接收器（部署执行器，必须保留）
                              ↓
                    nsenter → k8s/k3s-deploy.sh（拉代码/滚动更新/健康检查/失败回滚）
```

- **Server**：`drone/drone:2` 跑在现有 K3s，内置 SQLite（hostPath `k8s/drone-data/`），limits 128Mi。
- **Runner**：官方 `drone-runner-exec` 二进制，systemd 托管，直接在宿主机执行命令——无需 Docker（你只有 containerd），常驻内存可忽略。
- **单一入口**：Gitee 仓库只保留一条指向 Drone `:30080/hook` 的 WebHook；原来直连 `:8300/hook` 的那条已删除。每次 push 都会在 Drone 的 Builds 里留一条记录。
- **触发范围**：`.drone.yml` 仅在 `push` 和手动运行时触发，PR 事件不会触发生产部署。

## 关于 WebHook 验签（为什么没配 DRONE_WEBHOOK_SECRET）

- Drone 对**入站** Gitee 推送的验签用的是**每个仓库独立的 `repo.Signer`**：激活仓库时 Drone 自动生成一串 32 位随机 key，并自动在 Gitee 注册一条带该密码的 WebHook，推送时用 `X-Gitee-Token` 携带 HMAC-SHA256 签名比对。仓库 `techo` 已激活且 signer 已就位，验签**已经生效**。
- `DRONE_WEBHOOK_SECRET` 是另一回事：它用于 Drone **出站**系统 WebHook（Drone 主动通知外部系统的签名），对「Gitee → Drone」这条入站链路不起作用。因此**不配置**它——配了也不会保护本链路，反而引入误解。
- 验证依据：Drone 源码 `go-scm/scm/driver/gitee/webhook.go` 的 `Parse()` 用 `fn(hook)`（即 `repo.Signer`）做 HMAC 校验；key 为空时才跳过验签。

> ⚠️ 8300 接收器服务（webhook-receiver）**不能删**：Drone 的 `.drone.yml` 最后一步就是 `curl 127.0.0.1:8300/hook`，它是 Drone 的下游执行器。我们只删 Gitee 侧直连 8300 的那条 WebHook，服务器上的 8300 服务照常运行。

> ⚠️ exec runner 官方已归档（功能稳定但不再更新）。它不适合跑不可信代码，本项目只执行自己仓库的部署脚本，属于官方推荐的「需要主机访问的子集」场景，安全边界吻合。若日后要跑第三方 PR，再换 Docker runner。

## 一次性配置（约 10 分钟）

### 1. Gitee 建 OAuth 应用

Gitee → 设置 → 第三方应用 → 创建应用：

| 字段 | 值 |
|---|---|
| 应用主页 | `http://45.91.139.246:30080`（须与 `DRONE_SERVER_HOST` 完全一致） |
| 回调地址 | `http://45.91.139.246:30080/login` |

记下 **Client ID** 和 **Client Secret**。

> 当前服务器已按上面这对地址完成配置（2026-11-26），Gitee OAuth 已生效；
> 若改用域名，需同步修改 Secret 里的 `DRONE_SERVER_HOST` 并重启 server。

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

1. 浏览器打开 `http://45.91.139.246:30080`（或你的 CI 域名），用 Gitee 账号登录；
2. Repos 页找到 `techo.git`，点 **Activate**（激活时 Drone 会自动在 Gitee 注册 WebHook 并写好验签密码）；
3. Builds 页点 **Run pipeline**，分支选 `main` → **Run**；这就是手动 Build Now 按钮；
4. 实时日志里能看到「已提交到部署队列」和部署结果。

### 5. push 自动触发（当前状态：已配置）

Gitee 仓库 `donghaichen/techo` → 管理 → WebHooks，当前只应保留**一条**：

| 字段 | 值 |
|---|---|
| URL | `http://45.91.139.246:30080/hook` |
| 事件 | Push |
| WebHook 密码 | 留空即可——Drone 激活仓库时已用 `repo.Signer` 自动创建带密码的那条，**不要手动再建一条** |

直连 `http://45.91.139.246:8300/hook?token=...` 的旧 WebHook **已删除**（2026-11-26）。所有部署统一走 Drone：push → Drone build → curl 8300 → deploy。这样每次 push 都会在 Builds 列表留下可追溯的记录。

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
| Pod 反复重启，日志报 `Invalid port configuration` | `DRONE_SERVER_HOST` 带端口时，容器必须监听同一端口：`drone.yaml` 里 `containerPort`/`hostPort` 均为 30080，且 env 有 `DRONE_SERVER_PORT=:30080`（缺一不可） |
| 登录跳回 Gitee 报 redirect_uri 不符 | OAuth 回调地址与 `DRONE_SERVER_HOST` 必须完全一致（含 http/端口） |
| Builds 页显示 `no runners available` | runner 没连上：`tail /var/log/drone-runner-exec/log.txt`，核对 `DRONE_RPC_SECRET` 与 server Secret 一致 |
| 点运行后日志卡在「已提交队列」 | 检查 `tail -f scripts/k3s-deploy.log`，多半是 webhook token 文件或 8300 接收器问题 |
| Gitee 仓库列表为空 | OAuth 应用权限不足，或该仓库不属于登录账号 |

## 与 Gitee Go 的关系

`.workflow/ci.yml`（Gitee Go 流水线）与本方案都能提供手动按钮，**二选一即可**：

- **Drone（本方案）**：开源、自建、不依赖云端额度，代码和状态都在自己服务器；
- **Gitee Go**：纯云端零运维，但闭源、依赖云端额度与主机组 agent。

若要启用 Gitee Go，需先停用 Drone 的 Gitee WebHook（管理 → WebHooks → 禁用那条 `:30080/hook`），避免 push 触发两次部署。当前仓库已切到 Drone 单一入口，`.workflow/ci.yml` 保留但不接 WebHook。
