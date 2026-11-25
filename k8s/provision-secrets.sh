#!/bin/bash
# K3s 凭据自动配置（幂等，可重复执行）
# 原则：凭据缺失时随机生成；统一存放在本目录 secrets/（.gitignore 已忽略，不入库）；
#       不写 /root、/www/server 等系统目录；Dashboard 只用自带登录界面，不配 Basic Auth。
# 重新生成某凭据：删除 secrets/ 下对应文件后重跑本脚本。
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}

DIR="$(cd "$(dirname "$0")" && pwd)/secrets"
mkdir -p "$DIR"
chmod 700 "$DIR"

# 1) Dashboard 登录 Token（有效期 1 年）
if [ ! -s "$DIR/dashboard-token.txt" ]; then
  kubectl -n kubernetes-dashboard create token admin-user --duration=8760h > "$DIR/dashboard-token.txt"
  echo "已生成 Dashboard Token: $DIR/dashboard-token.txt"
fi

# 2) WebHook Token（Gitee WebHook 触发地址专用，随机 48 位十六进制）
if [ ! -s "$DIR/webhook-token.txt" ]; then
  openssl rand -hex 24 > "$DIR/webhook-token.txt"
  echo "已生成 WebHook Token: $DIR/webhook-token.txt"
fi

# WebHook Token 与运行中的接收器不一致时（首次部署或更换 token），写入并重启接收器
TOKEN=$(cat "$DIR/webhook-token.txt")
CURRENT=$(kubectl -n pysite get deploy webhook-receiver \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="WEBHOOK_TOKEN")].value}' 2>/dev/null || true)
if [ "$CURRENT" != "$TOKEN" ]; then
  sed "s#<WEBHOOK_TOKEN>#$TOKEN#" "$(dirname "$0")/webhook.yaml" | kubectl apply -f - >/dev/null
  kubectl -n pysite rollout restart deploy/webhook-receiver >/dev/null
  echo "WebHook Token 已写入 webhook-receiver 并重启生效"
fi

chmod 600 "$DIR"/*
