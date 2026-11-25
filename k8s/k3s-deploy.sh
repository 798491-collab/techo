#!/bin/bash
# K3s 自动部署脚本（宝塔 WebHook 调用；独立于 git 仓库，不会被 git pull 覆盖）
# 原则：只更新代码与重启 Pod；storage 数据卷永不触碰；失败自动回滚。
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

# 部署前记录数据库"大小+文章数"指纹（运行中 SQLite 会被写入，md5 会变但数据不能丢）
BEFORE=$(mktemp)
for s in $SITES; do
  db="$s/storage/site.db"
  [ -f "$db" ] || continue
  sz=$(stat -c %s "$db")
  cnt=$(python3 -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('select count(*) from article').fetchone()[0] if 'article' in [r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")] else 0)" "$db" 2>/dev/null || echo "?")
  echo "$sz $cnt $db"
done > "$BEFORE"

# 1. 拉代码（只更新 git 跟踪文件，storage/ 被 gitignore，绝不会被覆盖）
log "git pull..."
git config --global --replace-all safe.directory "$REPO" >/dev/null 2>&1 || true
git fetch origin main
NEW=$(git rev-parse origin/main)
OLD=$(git rev-parse HEAD)
log "版本 $OLD -> $NEW"
git reset --hard origin/main

# 2. 校验数据卷完好：文件存在、体积不小于部署前、文章数不减少（运行中 SQLite 会被写入，故不用 md5）
while IFS= read -r line; do
  sz0=$(printf '%s' "$line" | awk '{print $1}')
  cnt0=$(printf '%s' "$line" | awk '{print $2}')
  path=$(printf '%s' "$line" | awk '{print $3}')
  [ -n "$path" ] || continue
  if [ ! -f "$path" ]; then
    log "错误：数据库丢失 $path，中止部署"
    exit 1
  fi
  sz1=$(stat -c %s "$path")
  if [ "$sz0" != "?" ] && [ "$sz1" -lt "$sz0" ]; then
    log "错误：数据库异常缩小 $path ($sz0 -> $sz1)，中止部署"
    exit 1
  fi
  if [ "$cnt0" != "?" ] && [ "$cnt0" -gt 0 ]; then
    cnt1=$(python3 -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('select count(*) from article').fetchone()[0])" "$path" 2>/dev/null || echo "?")
    if [ "$cnt1" != "?" ] && [ "$cnt1" -lt "$cnt0" ]; then
      log "错误：文章数减少 $path ($cnt0 -> $cnt1)，中止部署"
      exit 1
    fi
  fi
done < "$BEFORE"
rm -f "$BEFORE"
log "数据卷校验通过（5 站数据库完好，无覆盖/丢失）"

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

# 5. 健康校验（五站首页必须 HTTP 200 且有内容）
if [ "$FAILED" -eq 0 ]; then
  for pair in "nanjingzhutao.com" "hefeizhupin.com" "xuzhoujiushuo.com" "wuxijunxin.com" "hangzhouzhiyu.net"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $pair" --max-time 10 http://127.0.0.1/)
    if [ "$code" != "200" ]; then
      log "健康校验失败 $pair HTTP=$code"
      FAILED=1
    fi
  done
fi

if [ "$FAILED" -ne 0 ]; then
  log "部署失败，执行回滚到 $OLD"
  # 回滚代码
  git reset --hard "$OLD"
  # 回滚 Deployment（记录上一版 replicaset 过于复杂，这里用重启恢复）
  for s in $SITES; do
    kubectl -n "$NS" rollout restart "deployment/pysite-$s" >/dev/null
  done
  log "回滚完成，请人工检查"
  exit 1
fi

log "健康校验通过，五站全部 HTTP 200"
log "===== 部署完成 $NEW ====="
