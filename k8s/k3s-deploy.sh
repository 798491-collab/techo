#!/bin/bash
# K3s 自动部署脚本（由 K3s 内 webhook 接收器调用；独立于 git 仓库，不会被 git pull 覆盖）
# 原则：只更新代码与重启 Pod；sites/<站>/storage/ 是容器挂载的数据卷，git 永不触碰。
set -euo pipefail

REPO=/www/wwwroot/pysite
LOG=$REPO/scripts/k3s-deploy.log
HISTORY=$REPO/scripts/release-history.txt
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
# 任何未预期退出（set -e 触发）都留下一行带行号的日志，避免再出现静默死亡
trap 'rc=$?; if [ $rc -ne 0 ] && [ $rc -ne 1 ]; then log "部署脚本异常退出（第 $LINENO 行，exit=$rc）"; fi' EXIT

# 0. 凭据自动配置（幂等：WebHook Token / 五站后台密码缺失时随机生成，
#    并统一登记到 k8s/secrets/credentials.txt）
bash "$REPO/k8s/provision-secrets.sh" 2>&1 | while IFS= read -r l; do log "凭据: $l"; done

# 1. 拉代码（storage/ 被 gitignore，git reset --hard 不会碰挂载的数据卷）
log "git pull..."
git config --global --replace-all safe.directory "$REPO" >/dev/null 2>&1 || true
git fetch origin main
NEW=$(git rev-parse origin/main)
OLD=$(git rev-parse HEAD)
log "版本 $OLD -> $NEW"
git reset --hard origin/main

# 1.5 依赖自检自愈：venv/lib/python3.10/site-packages 是宿主机挂载给五站 Pod 的
#     运行时依赖目录（不入 Git）。git 在跨越「删除 venv」的提交之间 reset 时会把
#     曾被 Git 跟踪的部分包文件删掉，导致 Pod ImportError / CrashLoopBackOff。
#     这里做导入自检：缺包或固定版本 dist-info 不在 → 清空后按 requirements.txt 重装。
SP="$REPO/venv/lib/python3.10/site-packages"
REQ="$REPO/requirements.txt"
NEED_INSTALL=0
python3 - "$SP" "$REQ" <<'PY' || NEED_INSTALL=1
import sys, pathlib
sp, req = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
# 仅做 dist-info 全量核对（requirements.txt 里每个 pin 都必须有对应 dist-info）。
# 不做任何真实 import：本检查可能运行在 webhook 接收器 Pod 的小内存 cgroup 里，
# 导入 fastapi/PIL 等重包会被 OOM 杀掉（dist-info 校验零内存开销，且正是
# git reset 跨删除提交后最可靠的缺失信号）。
missing = []
for line in req.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "==" not in line:
        continue
    name, ver = line.split("==", 1)
    if not any(sp.glob(f"{name}-{ver}.dist-info")):
        missing.append(line)
if missing:
    print("missing dist-info:", ", ".join(missing[:5]))
    sys.exit(1)
PY
if [ "$NEED_INSTALL" = "1" ]; then
  log "依赖缺失/版本不符，按 requirements.txt 重装 site-packages..."
  rm -rf "$SP" && mkdir -p "$SP"
  # 默认源偶发卡死：先试清华镜像（60s 超时、3 次重试），失败再回退官方源
  if ! pip3 install --no-cache-dir --timeout 60 --retries 3 \
      -i https://pypi.tuna.tsinghua.edu.cn/simple --target="$SP" -r "$REQ" >>"$LOG" 2>&1; then
    log "镜像源安装失败，回退官方源重试..."
    rm -rf "$SP" && mkdir -p "$SP"
    pip3 install --no-cache-dir --timeout 60 --retries 3 --target="$SP" -r "$REQ" >>"$LOG" 2>&1 \
      || { log "错误：依赖重装失败，中止部署"; exit 1; }
  fi
  log "依赖重装完成（$(ls "$SP" | wc -l) 项）"
fi

# 2. 数据卷就绪检查（轻量：只确认五站数据库存在且非空，防止仓库/目录结构异常）
for s in $SITES; do
  db="sites/$s/storage/site.db"
  if [ ! -s "$db" ]; then
    log "错误：数据库缺失或为空 sites/$s/storage/site.db，中止部署"
    exit 1
  fi
done
log "数据卷就绪（5 站 site.db 存在且非空）"

# 2.1 统一默认 favicon：仓库 logo.svg -> 各站 uploads/site-logo.svg（数据卷，git 不触碰）
#     并把 setting.site_favicon 指向它；只在值不同时写库，避免无谓变更
if [ -s "$REPO/logo.svg" ]; then
  for s in $SITES; do
    mkdir -p "sites/$s/storage/uploads"
    cp -f "$REPO/logo.svg" "sites/$s/storage/uploads/site-logo.svg"
    chmod 644 "sites/$s/storage/uploads/site-logo.svg"
    python3 - "$s" <<'PY' || true
import sqlite3, sys
site = sys.argv[1]
db = f"sites/{site}/storage/site.db"
want = "/uploads/site-logo.svg"
try:
    conn = sqlite3.connect(db, timeout=10)
    row = conn.execute("select value from setting where key='site_favicon'").fetchone()
    if row is None:
        conn.execute("insert into setting(key,value) values('site_favicon',?)", (want,))
    elif row[0] != want:
        conn.execute("update setting set value=? where key='site_favicon'", (want,))
    conn.commit(); conn.close()
except Exception:
    pass
PY
  done
  log "默认 favicon 已同步（仓库 logo.svg -> 五站 uploads/site-logo.svg）"
fi

# 3. 应用 Service（ClusterIP 固定 IP，作为 nginx 反代入口）
#    必须在 Deployment 之前：Service 的 selector 会先指向旧 Pod，ClusterIP 立即可用，
#    nginx 切流后滚动更新期间新旧 Pod 都由 Service 承接，全程无 502。
for s in $SITES; do
  kubectl -n "$NS" apply -f "$REPO/k8s/service-$s.yaml" >/dev/null
done
log "五站 Service（ClusterIP）已就绪"

# 4. 发版：apply 仓库 deploy YAML，让 YAML 成为唯一真相源
#    配置（resources / 探针 / 更新策略 / hostPort 等）全部以仓库 YAML 为准，
#    每次部署 apply 一次，消除「线上与 YAML 不一致」的配置漂移。
#    把 commit / 说明 / 时间通过占位符注入 Pod 模板注记，触发滚动更新 = 一个新修订版本；
#    `kubectl rollout history` 里即可看到版本号与时间，并支持一键回滚。
SUBJ=$(git log -1 --format='%s' "$NEW" | sed 's/["\\]/ /g')
AUTHOR=$(git log -1 --format='%an' "$NEW" | sed 's/["\\]/ /g')
DEPLOY_AT=$(date '+%F %T')
for s in $SITES; do
  sed -e "s|__COMMIT__|$NEW|g" -e "s|__SUBJECT__|$SUBJ|g" -e "s|__DEPLOYED_AT__|$DEPLOY_AT|g" \
    "$REPO/k8s/deploy-$s.yaml" | kubectl -n "$NS" apply -f - >/dev/null
done
log "已发版 $NEW「$SUBJ」($AUTHOR)，五站滚动更新中（RollingUpdate maxUnavailable=0）"

# 5. 同步 nginx 反代配置：仓库 scripts/nginx/*.conf -> 服务器 vhost 目录
#    由 ClusterIP 承接流量（不再依赖 hostNetwork/hostPort），nginx 只在这层保留一份。
NGINX_VHOST=/www/server/panel/vhost/nginx/pysite
if [ -d "$NGINX_VHOST" ]; then
  cp "$REPO"/scripts/nginx/*.conf "$NGINX_VHOST/" || log "警告：nginx 配置复制失败"
  if nginx -t >/dev/null 2>&1; then
    nginx -s reload >/dev/null 2>&1 && log "nginx 反代已切换到 ClusterIP 并 reload"
  else
    log "警告：nginx -t 校验失败，未 reload，请人工检查"
  fi
fi

# 6. 等待全部就绪（超时 120s）
FAILED=0
for s in $SITES; do
  if ! kubectl -n "$NS" rollout status "deployment/pysite-$s" --timeout=120s >/dev/null 2>&1; then
    log "站点 $s 启动失败"
    FAILED=1
  fi
done

# 7. 健康校验（经 ClusterIP 访问五站首页，必须 HTTP 200）
#    ClusterIP 固定：nanjing .101 / hefei .102 / xuzhou .103 / wuxi .104 / hangzhou .105
if [ "$FAILED" -eq 0 ]; then
  octet=101
  for s in $SITES; do
    ip="10.43.100.$octet"
    port=$((8100 + octet - 100))
    octet=$((octet + 1))
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$ip:$port/")
    if [ "$code" != "200" ]; then
      log "健康校验失败 $s (ClusterIP $ip:$port) HTTP=$code"
      FAILED=1
    fi
  done
fi

if [ "$FAILED" -ne 0 ]; then
  log "部署失败，执行回滚到 $OLD"
  git reset --hard "$OLD"
  for s in $SITES; do
    kubectl -n "$NS" rollout undo "deployment/pysite-$s" >/dev/null 2>&1 || \
      kubectl -n "$NS" rollout restart "deployment/pysite-$s" >/dev/null
  done
  echo "[$(date '+%F %T')] FAIL  $NEW -> 回滚 $OLD  $SUBJ" >> "$HISTORY"
  log "回滚完成，请人工检查"
  exit 1
fi

log "健康校验通过，五站全部 HTTP 200"
log "===== 部署完成 $NEW ====="
# 发版清单：每次成功发版追加一行（时间 版本号 提交说明 作者），即「发版记录」
mkdir -p "$(dirname "$HISTORY")"
echo "[$(date '+%F %T')] OK    $NEW  $SUBJ  ($AUTHOR)" >> "$HISTORY"
