#!/bin/bash
# K3s 凭据自动配置（幂等，可重复执行）
# 原则：凭据缺失时随机生成；统一登记在 secrets/credentials.txt（MySQL 安装打印临时密码的模式）；
#       secrets/ 已 gitignore 不入库，不写 /root、/www/server 等系统目录。
# 重新生成某凭据：删除 secrets/ 下对应文件后重跑本脚本（或随下次部署自动补齐）。
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}

K8S_DIR="$(cd "$(dirname "$0")" && pwd)"
DIR="$K8S_DIR/secrets"
REPO="$(dirname "$K8S_DIR")"
SITES='nanjing hefei xuzhou wuxi hangzhou'
mkdir -p "$DIR"
chmod 700 "$DIR"

gen_pwd() { openssl rand -base64 18 | tr '+/' '-_' | tr -d '=\n'; }   # 24 位，URL/JSON/Shell 安全

# 1) WebHook Token（Gitee WebHook 触发地址专用，随机 48 位十六进制）
if [ ! -s "$DIR/webhook-token.txt" ]; then
  openssl rand -hex 24 > "$DIR/webhook-token.txt"
  echo "已生成 WebHook Token: $DIR/webhook-token.txt"
fi
TOKEN=$(cat "$DIR/webhook-token.txt")
CURRENT=$(kubectl -n pysite get deploy webhook-receiver \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="WEBHOOK_TOKEN")].value}' 2>/dev/null || true)
if [ "$CURRENT" != "$TOKEN" ]; then
  sed "s#<WEBHOOK_TOKEN>#$TOKEN#" "$K8S_DIR/webhook.yaml" | kubectl apply -f - >/dev/null
  kubectl -n pysite rollout restart deploy/webhook-receiver >/dev/null
  echo "WebHook Token 已写入 webhook-receiver 并重启生效"
fi

# 2) 五站后台管理员密码：部署时确保存在（与应用内首启生成规则一致：SECRET_KEY 64hex + ADMIN_PASSWORD 24 位）
for s in $SITES; do
  env="$REPO/sites/$s/.env"
  if [ ! -f "$env" ]; then
    KEY=$(openssl rand -hex 32)
    P=$(gen_pwd)
    printf '# 本站点密钥（部署时自动生成；删除后重启会重新生成，登录态与后台密码都会变）\n# 此文件不进 Git，请妥善备份\nSECRET_KEY=%s\nADMIN_PASSWORD=%s\n' "$KEY" "$P" > "$env"
    chmod 600 "$env"
    echo "已生成站点凭据: sites/$s/.env"
  elif ! grep -qE '^ADMIN_PASSWORD=..+' "$env"; then
    P=$(gen_pwd)
    sed -i '/^ADMIN_PASSWORD= *$/d;/^ADMIN_PASSWORD=$/d' "$env"
    printf 'ADMIN_PASSWORD=%s\n' "$P" >> "$env"
    chmod 600 "$env"
    echo "已补齐站点后台密码: sites/$s/.env"
  fi
done

# 3) 凭据总清单（每次部署刷新，始终与实际一致；相当于 MySQL 的 initial password 文件）
{
  echo "# 凭据清单（部署脚本自动生成并刷新；此文件不入 Git，请妥善保管）"
  echo "# 生成时间: $(date '+%F %T')"
  echo
  if [ -s "$DIR/webhook-token.txt" ]; then
    echo "[WebHook Token]（Gitee WebHook 触发地址: http://<服务器IP>:8300/hook?token=<此值>）"
    echo "  token: $(cat "$DIR/webhook-token.txt")"
    echo
  fi
  echo "[网站后台]（各站 http://<域名>/admin/，账号均为 admin）"
  for s in $SITES; do
    P=$(sed -n 's/^ADMIN_PASSWORD=//p' "$REPO/sites/$s/.env" 2>/dev/null | head -1 | tr -d '"' | tr -d "'")
    echo "  $s: $P"
  done
} > "$DIR/credentials.txt"
chmod 600 "$DIR"/* 2>/dev/null || true
echo "凭据清单已刷新: $DIR/credentials.txt"
