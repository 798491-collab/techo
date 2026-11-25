#!/bin/bash
# K3s 自动部署脚本（由 K3s 内 webhook 接收器调用；独立于 git 仓库，不会被 git pull 覆盖）
# 原则：只更新代码与重启 Pod；sites/<站>/storage/ 是容器挂载的数据卷，git 永不触碰。
set -euo pipefail

REPO=/www/wwwroot/pysite
LOG=$REPO/scripts/k3s-deploy.log
SITES='nanjing hefei xuzhou wuxi hangzhou'
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
NS=pysite

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# 并发锁
exec 9>/tmp/pysite-k3s-deploy.lock
if ! flock -n 9; then
  log "另一个部署正在进行，跳过"
  exit 0
fi

cd "$REPO"
log "===== K3s 部署开始 ====="

# 0. 凭据自动配置（幂等：Dashboard Token / WebHook Token 缺失时随机生成，存 k8s/secrets/）
bash "$REPO/k8s/provision-secrets.sh" 2>&1 | while IFS= read -r l; do log "凭据: $l"; done

# 1. 拉代码（storage/ 被 gitignore，git reset --hard 不会碰挂载的数据卷）
log "git pull..."
git config --global --replace-all safe.directory "$REPO" >/dev/null 2>&1 || true
git fetch origin main
NEW=$(git rev-parse origin/main)
OLD=$(git rev-parse HEAD)
log "版本 $OLD -> $NEW"
git reset --hard origin/main

# 2. 数据卷就绪检查（轻量：只确认五站数据库存在且非空，防止仓库/目录结构异常）
for s in $SITES; do
  db="sites/$s/storage/site.db"
  if [ ! -s "$db" ]; then
    log "错误：数据库缺失或为空 sites/$s/storage/site.db，中止部署"
    exit 1
  fi
done
log "数据卷就绪（5 站 site.db 存在且非空）"

# 3. 滚动重启五站（代码通过 hostPath 挂载，重启即加载新代码）
for s in $SITES; do
  kubectl -n "$NS" rollout restart "deployment/pysite-$s" >/dev/null
done
log "已触发五站滚动重启"

# 4. 等待全部就绪（超时 120s）
FAILED=0
for s in $SITES; do
  if ! kubectl -n "$NS" rollout status "deployment/pysite-$s" --timeout=120s >/dev/null 2>&1; then
    log "站点 $s 启动失败"
    FAILED=1
  fi
done

# 5. 健康校验（五站首页必须 HTTP 200）
if [ "$FAILED" -eq 0 ]; then
  i=1
  for s in $SITES; do
    port=$((8100 + i)); i=$((i + 1))
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/")
    if [ "$code" != "200" ]; then
      log "健康校验失败 $s (127.0.0.1:$port) HTTP=$code"
      FAILED=1
    fi
  done
fi

if [ "$FAILED" -ne 0 ]; then
  log "部署失败，执行回滚到 $OLD"
  git reset --hard "$OLD"
  for s in $SITES; do
    kubectl -n "$NS" rollout restart "deployment/pysite-$s" >/dev/null
  done
  log "回滚完成，请人工检查"
  exit 1
fi

log "健康校验通过，五站全部 HTTP 200"
log "===== 部署完成 $NEW ====="
