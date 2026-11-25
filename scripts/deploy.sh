#!/bin/bash
# PySite 自动部署脚本（宝塔 WebHook / 手动均可）
# 原则：只更新 Git 跟踪的代码文件，绝不覆盖未跟踪的生产数据
#   - storage/ 是唯一持久化目录（db / 上传 / 缓存 / 日志 / 会话 / 临时），容器化只挂这一个卷
#   - 旧 data / runtime / uploads / var 里的数据自动补进 storage，确认无缺后清理
#   - 老部署升级时从 data / runtime / var 中选最新的库迁到 storage，旧快照留 .legacy
set -e

REPO=/www/wwwroot/pysite
DEPLOY_LOG=$REPO/scripts/deploy.log
mkdir -p "$REPO/scripts"
SITES='nanjing hefei xuzhou wuxi hangzhou'

log() { echo "[$(date '+%F %T')] $*" | tee -a "$DEPLOY_LOG"; }

git config --global --replace-all safe.directory "$REPO" >/dev/null 2>&1 || true

# 防止 WebHook 重复触发导致并发部署
exec 9>"$REPO/.deploy.lock"
if ! flock -n 9; then
  log "另一个部署正在进行，跳过本次触发"
  exit 0
fi

cd "$REPO"
log "===== 开始部署 ====="

# 先停站点，避免复制正在写入的 SQLite
"$REPO/scripts/pysite" stop || true

# 部署前快照：已有数据库和上传文件，结束后必须逐个对上
SNAPSHOT=$(mktemp)
for s in $SITES; do
  for db in "$s/storage/site.db" "$s/data/site.db" "$s/runtime/site.db" "$s/var/site.db"; do
    [ -f "$db" ] && md5sum "$db"
  done
  for d in "$s/storage/uploads" "$s/data/uploads" "$s/uploads"; do
    [ -d "$d" ] || continue
    find "$d" -type f ! -name '.gitkeep' -print0 | sort -z | xargs -0 -r md5sum
  done
done > "$SNAPSHOT"
cp "$SNAPSHOT" "$DEPLOY_LOG.snapshot"

git fetch origin main

# 关键：先备份未跟踪的生产数据目录，reset 后再覆盖式恢复，杜绝误删与目录嵌套
PROTECT=/tmp/pysite-protect-$$
mkdir -p "$PROTECT"
for s in $SITES; do
  mkdir -p "$PROTECT/$s"
  for d in uploads runtime data storage var; do
    if [ -d "$s/$d" ]; then
      cp -a "$s/$d" "$PROTECT/$s/$d"
    fi
  done
  [ -f "$s/.env" ] && cp -a "$s/.env" "$PROTECT/$s/.env"
done

git reset --hard origin/main

# 恢复生产数据：用备份填回，已有文件以备份为准
copy_missing() {
  local src="$1" dest="$2" f rel target
  [ -d "$src" ] || return 0
  mkdir -p "$dest"
  find "$src" -type f ! -name '.gitkeep' -print0 | while IFS= read -r -d '' f; do
    rel="${f#"$src"/}"
    target="$dest/$rel"
    if [ ! -e "$target" ]; then
      mkdir -p "$(dirname "$target")"
      cp -a "$f" "$target"
    fi
  done
}

for s in $SITES; do
  if [ -d "$PROTECT/$s" ]; then
    mkdir -p "$s"
    for d in uploads runtime data storage var; do
      if [ -d "$PROTECT/$s/$d" ]; then
        mkdir -p "$s/$d"
        cp -a "$PROTECT/$s/$d/." "$s/$d/"
      fi
    done
    [ -f "$PROTECT/$s/.env" ] && cp -a "$PROTECT/$s/.env" "$s/.env"
  fi
  # seed.json 是入库的代码资源，不能被备份里的旧版覆盖
  git checkout -- "$s/storage/seed.json" 2>/dev/null || true
  mkdir -p "$s/storage/logs" "$s/storage/cache" "$s/storage/temp" "$s/storage/sessions" "$s/storage/uploads"

  # 老部署升级：从 data / runtime / var 里挑最新的库迁到 storage，旧快照留 .legacy
  best_db="$s/storage/site.db"
  for cand in "$s/data/site.db" "$s/runtime/site.db" "$s/var/site.db"; do
    [ -s "$cand" ] || continue
    if [ ! -s "$best_db" ] || [ "$cand" -nt "$best_db" ]; then
      best_db="$cand"
    fi
  done
  if [ "$best_db" != "$s/storage/site.db" ]; then
    [ -s "$s/storage/site.db" ] && mv "$s/storage/site.db" "$s/storage/site.db.legacy-$(date +%Y%m%d%H%M%S)"
    cp -a "$best_db" "$s/storage/site.db"
    log "$s 已从 $best_db 迁移数据库到 storage"
  else
    log "$s 已有 storage/site.db，不覆盖"
  fi

  # 旧目录数据补齐到 storage（copy_missing 不删原文件，校验环节才能确认无丢失）
  copy_missing "$s/uploads" "$s/storage/uploads"
  copy_missing "$s/data/uploads" "$s/storage/uploads"
  for d in logs cache sessions temp; do
    copy_missing "$s/data/$d" "$s/storage/$d"
    copy_missing "$s/runtime/$d" "$s/storage/$d"
  done
  for d in logs sessions cache; do copy_missing "$s/var/$d" "$s/storage/$d"; done
  copy_missing "$s/var/tmp" "$s/storage/temp"
done
rm -rf "$PROTECT"

# 已有文件必须和部署前一致，通过后才删除 var。此时站点仍是停着的，数据库不会被进程改写。
keep_var=0
while IFS= read -r line; do
  sum=${line%% *}
  path=${line#* }
  path=${path# }
  [ -n "$path" ] || continue
  if [ ! -f "$path" ]; then
    log "部署后文件丢失: $path"
    keep_var=1
    continue
  fi
  now=$(md5sum "$path" | awk '{print $1}')
  if [ "$now" != "$sum" ]; then
    log "部署后文件被改写: $path"
    keep_var=1
  fi
done < "$SNAPSHOT"
rm -f "$SNAPSHOT"

legacy_uploads_ready() {
  local s="$1" base src dest rel sum_src sum_dest
  for base in "$s/data/uploads" "$s/uploads"; do
    [ -d "$base" ] || continue
    while IFS= read -r -d '' src; do
      [ "$(basename "$src")" = ".gitkeep" ] && continue
      rel="${src#"$base"/}"
      dest="$s/storage/uploads/$rel"
      if [ ! -f "$dest" ]; then
        log "$s 上传文件尚未进入 storage/uploads: $rel"
        return 1
      fi
      sum_src=$(md5sum "$src" | awk '{print $1}')
      sum_dest=$(md5sum "$dest" | awk '{print $1}')
      if [ "$sum_src" != "$sum_dest" ]; then
        log "$s 上传文件与旧目录不一致，保留旧目录: $rel"
        return 1
      fi
    done < <(find "$base" -type f -print0)
  done
  return 0
}

if [ "$keep_var" -eq 0 ]; then
  for s in $SITES; do
    if [ -s "$s/storage/site.db" ] && [ -d "$s/var" ]; then
      case "$s/var" in
        "$s"/*) rm -rf "$s/var"; log "已删除 $s/var" ;;
      esac
    elif [ ! -s "$s/storage/site.db" ]; then
      log "$s 没有 storage 数据库，保留 var"
    fi
    if legacy_uploads_ready "$s"; then
      for d in data runtime uploads; do
        if [ -d "$s/$d" ]; then
          case "$s/$d" in
            "$s"/*) rm -rf "$s/$d"; log "已删除旧目录 $s/$d" ;;
          esac
        fi
      done
    else
      log "$s 保留旧目录，上传文件未确认一致"
    fi
  done
else
  log "校验未通过，保留所有旧目录，不删除任何生产数据"
fi

# 属主与权限
chown -R www:www "$REPO"
chmod +x "$REPO/scripts/pysite" "$REPO/scripts/deploy.sh"

# 同步 systemd unit 并重启。线上虚拟环境缺 Pillow 时，带处理参数的图片会直接回原图。
cp "$REPO/scripts/systemd/pysite@.service" /etc/systemd/system/pysite@.service
systemctl daemon-reload
if [ -x "$REPO/venv/bin/python" ] && ! "$REPO/venv/bin/python" -c "import PIL" >/dev/null 2>&1; then
  "$REPO/venv/bin/python" -m pip install pillow || log "Pillow 安装失败，图片会继续返回原图"
fi
"$REPO/scripts/pysite" restart

# 同步 nginx：只做整站反代，上传和主题文件由站点进程送出。
# include 指针由 pysite_sites.conf 统一管理；nginx -t 校验通过才 reload，失败则保留旧配置
NGINX_VHOST=/www/server/panel/vhost/nginx
if command -v nginx >/dev/null 2>&1 && [ -d "$NGINX_VHOST" ]; then
  mkdir -p "$NGINX_VHOST/pysite"
  cp -f "$REPO"/scripts/nginx/*.conf "$NGINX_VHOST/pysite/"
  if [ ! -f "$NGINX_VHOST/pysite_sites.conf" ]; then
    printf 'include %s/pysite/*.conf;\n' "$NGINX_VHOST" > "$NGINX_VHOST/pysite_sites.conf"
  fi
  if nginx -t >>"$DEPLOY_LOG" 2>&1; then
    nginx -s reload >>"$DEPLOY_LOG" 2>&1 && log "nginx 配置已同步并 reload" \
      || log "nginx reload 失败，请人工检查"
  else
    log "nginx -t 校验失败，跳过 reload（保留旧配置）"
  fi
fi

log "===== 部署完成 ====="
"$REPO/scripts/pysite" status | tee -a "$DEPLOY_LOG"
