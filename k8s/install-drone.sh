#!/bin/bash
# Drone CI 一键安装（面向本项目：K3s + containerd，无 Docker）
#   - server 跑在 K3s（drone.yaml），SQLite 落 hostPath
#   - exec runner 用官方二进制跑在宿主机，systemd 托管（约 20MB，常驻内存可忽略）
#   - pipeline (.drone.yml) 只做一件事：点按钮时 curl 现有 webhook 触发部署
# 用法：在服务器上 cd /www/wwwroot/pysite && sudo bash k8s/install-drone.sh
set -euo pipefail

REPO=/www/wwwroot/pysite
NS=pysite
RUNNER_DIR=/opt/drone-runner   # 二进制属系统组件，放 /opt；项目数据仍全在仓库内
DRONE_SERVER_HOST="${DRONE_SERVER_HOST:-}"   # 例：ci.example.com:30080 或 1.2.3.4:30080
GITEE_CLIENT_ID="${GITEE_CLIENT_ID:-}"
GITEE_CLIENT_SECRET="${GITEE_CLIENT_SECRET:-}"
ADMIN_USER="${ADMIN_USER:-}"                 # 你的 Gitee 用户名

echo "== Drone CI 安装 =="
command -v kubectl >/dev/null || { echo "缺少 kubectl"; exit 1; }

# ---------- 1. 交互补齐缺失参数 ----------
[ -n "$DRONE_SERVER_HOST" ] || read -rp "Drone 对外地址(域名或IP:端口): " DRONE_SERVER_HOST
[ -n "$GITEE_CLIENT_ID" ] || read -rp "Gitee OAuth 应用的 Client ID: " GITEE_CLIENT_ID
[ -n "$GITEE_CLIENT_SECRET" ] || read -rsp "Gitee OAuth 应用的 Client Secret: " GITEE_CLIENT_SECRET; echo
[ -n "$ADMIN_USER" ] || read -rp "你的 Gitee 用户名(设为管理员): " ADMIN_USER

RPC_SECRET=$(openssl rand -hex 16)
echo "RPC Secret 已生成（server 与 runner 共用）"

# ---------- 2. 创建 K8s Secret（含 webhook token，供 secret 注入）----------
WEBHOOK_TOKEN=""
if [ -f "$REPO/k8s/secrets/webhook-token.txt" ]; then
  WEBHOOK_TOKEN=$(tr -d '\r\n' < "$REPO/k8s/secrets/webhook-token.txt")
fi
if [ -z "$WEBHOOK_TOKEN" ]; then
  echo "未找到 k8s/secrets/webhook-token.txt，请先部署站点生成凭据"
  exit 1
fi

kubectl -n "$NS" create secret generic drone-secrets \
  --from-literal=DRONE_SERVER_HOST="$DRONE_SERVER_HOST" \
  --from-literal=DRONE_RPC_SECRET="$RPC_SECRET" \
  --from-literal=DRONE_GITEE_CLIENT_ID="$GITEE_CLIENT_ID" \
  --from-literal=DRONE_GITEE_CLIENT_SECRET="$GITEE_CLIENT_SECRET" \
  --from-literal=DRONE_USER_CREATE="username:$ADMIN_USER,admin:true" \
  --dry-run=client -o yaml | kubectl -n "$NS" apply -f -

# ---------- 3. 部署 Drone server ----------
kubectl apply -f "$REPO/k8s/drone.yaml"

# ---------- 4. 安装 exec runner（二进制，无 Docker）----------
mkdir -p "$RUNNER_DIR" /var/log/drone-runner-exec
RUNNER_URL="https://github.com/drone-runners/drone-runner-exec/releases/latest/download/drone_runner_exec_linux_amd64.tar.gz"
if [ ! -x "$RUNNER_DIR/drone-runner-exec" ]; then
  echo "下载 exec runner ..."
  curl -fsSL "$RUNNER_URL" -o /tmp/drone-runner-exec.tgz
  tar -xzf /tmp/drone-runner-exec.tgz -C /tmp drone-runner-exec
  install -m 0755 /tmp/drone-runner-exec "$RUNNER_DIR/drone-runner-exec"
  rm -f /tmp/drone-runner-exec.tgz /tmp/drone-runner-exec
fi

# exec runner 配置（key=value，非 bash；位置由 root 运行决定）
cat > /etc/drone-runner-exec/config <<EOF
DRONE_RPC_PROTO=http
DRONE_RPC_HOST=127.0.0.1:30080
DRONE_RPC_SECRET=$RPC_SECRET
DRONE_LOG_FILE=/var/log/drone-runner/log.txt
DRONE_RUNNER_NAME=pysite-exec
DRONE_RUNNER_CAPACITY=1
EOF
chmod 600 /etc/drone-runner-exec/config

"$RUNNER_DIR/drone-runner-exec" service install >/dev/null 2>&1 || true
"$RUNNER_DIR/drone-runner-exec" service start >/dev/null 2>&1 || \
  systemctl enable --now drone-runner-exec

# ---------- 5. 等待就绪 ----------
echo "等待 Drone server 就绪 ..."
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:30080/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done
kubectl -n "$NS" rollout status deploy/drone-server --timeout=90s || true

echo
echo "== 完成 =="
echo "Drone 地址: http://$DRONE_SERVER_HOST"
echo "用你的 Gitee 账号登录（首次登录需在 Repos 页激活 pysite 仓库）"
echo "之后即可在 Builds 页点 'Run pipeline'（等价 Jenkins Build Now）"
echo "Token 由 runner 直接从 k8s/secrets/webhook-token.txt 读取，无需在 Drone 配置 secret"
echo
echo "验证 runner: tail -f /var/log/drone-runner/log.txt"
