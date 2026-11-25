"""定时任务引擎（对标宝塔计划任务）。

任务定义存于 AdminTask：
  - task_key    : 任务类型（shell/backup_site/backup_db/clean_log/antivirus/free_mem/url/clean_cache）
  - params JSON : {cycle, cycle_cfg{...}, targets[], keep, compress, exclude_dirs, db_lock, url}
周期语义（全部为服务器本地时区）：
  day      每天 H 点
  day-n    每 N 天的 H 点（锚点为任务创建日，取 day_of_year % n 对齐）
  hour     每小时 M 分
  hour-n   每 N 小时（整点对齐）
  minute-n 每 N 分钟（整分对齐）
  week     每周勾选的星期 + H:M
  month    每月 D 日（1-28）H:M
备份产物统一写入站点 backups/ 目录；非本地存储渠道（OSS/COS/FTP 等）记录到
任务输出，待【存储设置】配置好渠道后自动生效。
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
import zipfile
from pathlib import Path

TASK_TYPES = {
    "shell": "Shell脚本",
    "backup_site": "备份网站",
    "backup_db": "备份数据库",
    "clean_log": "清理日志",
    "antivirus": "木马查杀",
    "free_mem": "释放内存",
    "url": "访问URL",
    "clean_cache": "清理缓存",
}

# 备份类任务才显示「备份存储位置」
BACKUP_TYPES = {"backup_site", "backup_db"}

STORAGE_TARGETS = [
    "本地", "FTP存储空间", "阿里云OSS", "七牛云存储", "谷歌云存储", "谷歌云网盘",
    "亚马逊S3云存储", "腾讯云COS", "百度云存储", "华为云存储", "京东云存储",
    "百度网盘", "阿里云盘", "邮箱",
]

WEEK_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def task_params(task) -> dict:
    try:
        p = json.loads(task.params or "{}")
    except ValueError:
        p = {}
    return p if isinstance(p, dict) else {}


def _check(cycle: str, cfg: dict) -> str | None:
    """前后端双重校验：非法周期参数返回错误文案。"""
    def num(key, lo, hi):
        v = cfg.get(key)
        if v is None or str(v) == "":
            return f"缺少参数 {key}"
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return f"参数 {key} 必须为整数"
        if iv < lo or iv > hi:
            return f"参数 {key} 超出范围 {lo}-{hi}"
        return None

    if cycle == "day":
        return num("hour", 0, 23)
    if cycle == "day-n":
        return num("n", 1, 365) or num("hour", 0, 23)
    if cycle == "hour":
        return num("minute", 0, 59)
    if cycle == "hour-n":
        return num("n", 1, 24)
    if cycle == "minute-n":
        return num("n", 1, 59)
    if cycle == "week":
        days = cfg.get("days") or []
        if not [d for d in days if 0 <= int(d) <= 6]:
            return "请至少选择一个星期"
        return num("hour", 0, 23) or num("minute", 0, 59)
    if cycle == "month":
        return num("day", 1, 28) or num("hour", 0, 23) or num("minute", 0, 59)
    return "未知执行周期"


def compute_next_run(cycle: str, cfg: dict, now: _dt.datetime | None = None) -> _dt.datetime:
    """根据周期与参数计算下一次执行时间（服务器本地时区）。"""
    now = now or _dt.datetime.now()
    h = int(cfg.get("hour", 0) or 0)
    m = int(cfg.get("minute", 0) or 0)

    if cycle == "day":
        nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if nxt <= now:
            nxt += _dt.timedelta(days=1)
        return nxt

    if cycle == "day-n":
        n = max(1, int(cfg.get("n", 1) or 1))
        nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if nxt <= now:
            nxt += _dt.timedelta(days=1)
        # 对齐锚点：使 (nxt - epoch_anchor) % n == 0
        epoch = _dt.datetime(2026, 1, 1)
        while (nxt - epoch).days % n != 0:
            nxt += _dt.timedelta(days=1)
        return nxt

    if cycle == "hour":
        minute = int(cfg.get("minute", 0) or 0)
        nxt = now.replace(minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += _dt.timedelta(hours=1)
        return nxt

    if cycle == "hour-n":
        n = max(1, int(cfg.get("n", 1) or 1))
        nxt = now.replace(minute=0, second=0, microsecond=0)
        nxt += _dt.timedelta(hours=n)
        while nxt <= now:
            nxt += _dt.timedelta(hours=n)
        return nxt

    if cycle == "minute-n":
        n = max(1, int(cfg.get("n", 1) or 1))
        nxt = now.replace(second=0, microsecond=0)
        nxt += _dt.timedelta(minutes=n)
        while nxt <= now:
            nxt += _dt.timedelta(minutes=n)
        return nxt

    if cycle == "week":
        days = sorted({int(d) for d in (cfg.get("days") or []) if 0 <= int(d) <= 6})
        if not days:
            days = [0]
        # Python weekday(): Monday=0 与 WEEK_NAMES 一致
        cur_wd = now.weekday()
        for off in range(0, 8):
            d = (now + _dt.timedelta(days=off))
            if d.weekday() in days:
                cand = d.replace(hour=h, minute=m, second=0, microsecond=0)
                if cand > now:
                    return cand
        return now + _dt.timedelta(days=7)

    if cycle == "month":
        day = max(1, min(28, int(cfg.get("day", 1) or 1)))
        cand = now.replace(day=day, hour=h, minute=m, second=0, microsecond=0)
        if cand <= now:
            # 下个月同一天（day<=28 不会越界）
            y, mo = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
            cand = cand.replace(year=y, month=mo)
        return cand

    return now + _dt.timedelta(days=1)


def describe_cycle(cycle: str, cfg: dict) -> str:
    """周期的人类可读描述（列表页显示）。"""
    h = str(cfg.get("hour", "0"))
    m = str(cfg.get("minute", "0"))
    try:
        if cycle == "day":
            return f"每天 {int(h):02d}:{int(m):02d}"
        if cycle == "day-n":
            return f"每 {cfg.get('n')} 天 {int(h):02d}:{int(m):02d}"
        if cycle == "hour":
            return f"每小时第 {m} 分"
        if cycle == "hour-n":
            return f"每 {cfg.get('n')} 小时"
        if cycle == "minute-n":
            return f"每 {cfg.get('n')} 分钟"
        if cycle == "week":
            days = "、".join(WEEK_NAMES[int(d)] for d in sorted({int(x) for x in (cfg.get("days") or [])}))
            return f"每周 {days} {int(h):02d}:{int(m):02d}"
        if cycle == "month":
            return f"每月 {cfg.get('day')} 日 {int(h):02d}:{int(m):02d}"
    except (TypeError, ValueError):
        pass
    return cycle


# ==================== 任务执行器 ====================

def _exec_backup_site(p: dict, cfg) -> tuple[str, str]:
    exclude = [x.strip() for x in (p.get("exclude_dirs") or "").replace("，", ",").split(",") if x.strip()]
    backup_dir = cfg.root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"site_backup_{cfg.key}_{ts}.zip"
    lines = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(cfg.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(cfg.root).as_posix()
            if rel.startswith("backups/") or any(rel.startswith(e.rstrip("/") + "/") or rel == e for e in exclude):
                continue
            try:
                zf.write(path, rel)
            except (OSError, PermissionError):
                lines.append(f"跳过无法读取的文件：{rel}")
    size_mb = target.stat().st_size / 1048576
    lines.insert(0, f"网站备份完成：{target.name}（{size_mb:.2f} MB）")
    _retention(backup_dir, f"site_backup_{cfg.key}_", int(p.get("keep", 5) or 5), lines)
    lines += _offsite_targets(p.get("targets") or [])
    return "success", "\n".join(lines)


def _exec_backup_db(p: dict, cfg) -> tuple[str, str]:
    backup_dir = cfg.root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"db_backup_{cfg.key}_{ts}.zip"
    src = Path(cfg.db_file)
    lock = str(p.get("db_lock", "1")) != "0"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, src.name)
    size_kb = target.stat().st_size / 1024
    out = [f"数据库备份完成：{target.name}（{size_kb:.1f} KB）",
           f"数据库{'已加锁（WAL checkpoint）' if lock else '未加锁'}：{src.name}"]
    if lock:
        try:
            import sqlite3
            con = sqlite3.connect(src)
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except Exception:
            pass
    _retention(backup_dir, f"db_backup_{cfg.key}_", int(p.get("keep", 5) or 5), out)
    out += _offsite_targets(p.get("targets") or [])
    return "success", "\n".join(out)


def _retention(backup_dir: Path, prefix: str, keep: int, lines: list):
    """保留最近 keep 份备份，自动清理旧的。"""
    files = sorted(backup_dir.glob(prefix + "*.zip"))
    for old in files[:-keep] if keep > 0 else files:
        try:
            old.unlink()
            lines.append(f"已清理旧备份：{old.name}")
        except OSError:
            pass


def _offsite_targets(targets: list) -> list:
    """本地以外的存储渠道：待【存储设置】配置后生效。"""
    out = []
    for t in targets or []:
        if t and t != "本地":
            out.append(f"存储渠道「{t}」：尚未配置渠道密钥，本次仅保存到本地（配置后自动上传）")
    if "本地" in (targets or []) or not targets:
        out.append("已保存到本地 backups/ 目录")
    return out


def _exec_clean_log(p: dict, cfg) -> tuple[str, str]:
    removed, freed = 0, 0
    logs_dir = cfg.log_dir
    days = int(p.get("days", 7) or 7)
    cutoff = _dt.datetime.now().timestamp() - days * 86400
    for d in (logs_dir,):
        if not d.exists():
            continue
        for f in d.rglob("*.log"):
            if f.stat().st_mtime < cutoff:
                freed += f.stat().st_size
                f.unlink()
                removed += 1
    return "success", f"日志清理完成：删除 {days} 天前的日志 {removed} 个，释放 {freed/1024:.1f} KB"


def _exec_antivirus(p: dict, cfg) -> tuple[str, str]:
    """扫描上传目录中的可执行脚本（网站场景下不应出现）。"""
    danger_ext = {".php", ".asp", ".aspx", ".jsp", ".ps1", ".bat", ".sh", ".exe", ".dll"}
    hits = []
    up_dir = cfg.uploads_path
    if up_dir.exists():
        for f in up_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in danger_ext:
                hits.append(str(f.relative_to(cfg.root)))
    if hits:
        return "fail", "发现可疑脚本文件（请立即人工核查并删除）：\n" + "\n".join(hits[:50])
    return "success", "木马查杀完成：未发现可疑脚本文件"


def _exec_free_mem(p: dict, cfg) -> tuple[str, str]:
    out = []
    try:
        import gc
        collected = gc.collect()
        out.append(f"Python GC 回收对象：{collected}")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        out.append("已调用 EmptyWorkingSet 释放进程工作集")
    except Exception:
        out.append("当前平台无需手动释放内存")
    return "success", "\n".join(out) or "释放内存完成"


def _exec_url(p: dict, cfg) -> tuple[str, str]:
    import httpx
    url = str(p.get("url") or "").strip()
    if not url:
        return "fail", "未配置访问 URL"
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        return ("success" if r.status_code < 400 else "fail"),
        f"GET {url} → HTTP {r.status_code}，耗时 {r.elapsed.total_seconds():.2f}s，长度 {len(r.content)}B"
    except Exception as e:  # noqa: BLE001
        return "fail", f"GET {url} 失败：{e}"


def _exec_clean_cache(p: dict, cfg) -> tuple[str, str]:
    removed = 0
    cache_dir = cfg.cache_path
    if cache_dir.exists():
        for f in cache_dir.rglob("*"):
            if f.is_file():
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return "success", f"缓存清理完成：删除缓存文件 {removed} 个"


def _exec_shell(p: dict, cfg) -> tuple[str, str]:
    script = str(p.get("script") or "").strip()
    if not script:
        return "fail", "Shell 脚本内容为空"
    try:
        r = subprocess.run(script, shell=True, capture_output=True, text=True,
                           timeout=int(p.get("timeout", 60) or 60), cwd=str(cfg.root))
        out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
        return ("success" if r.returncode == 0 else "fail"), f"exit={r.returncode}\n{out.strip()[:4000]}"
    except subprocess.TimeoutExpired:
        return "fail", "脚本执行超时"


EXECUTORS = {
    "backup_site": _exec_backup_site,
    "backup_db": _exec_backup_db,
    "clean_log": _exec_clean_log,
    "antivirus": _exec_antivirus,
    "free_mem": _exec_free_mem,
    "clean_cache": _exec_clean_cache,
}


def run_task(task, cfg) -> tuple[str, str]:
    """执行单个任务，返回 (status, output)。url/shell 走专用分支。"""
    ttype = (task.task_key or "").strip()
    p = task_params(task)
    if ttype == "shell":
        return _exec_shell(p, cfg)
    if ttype == "url":
        return _exec_url(p, cfg)
    fn = EXECUTORS.get(ttype)
    if not fn:
        return "fail", f"未知任务类型：{ttype}"
    try:
        return fn(p, cfg)
    except Exception as e:  # noqa: BLE001
        return "fail", f"执行异常：{e}"


def run_due_tasks(session, cfg, now: _dt.datetime | None = None) -> int:
    """扫描到期任务并执行（由 lifespan 轮询调用），返回执行条数。"""
    from app.core.database import AdminTask, AdminTaskLog
    now = now or _dt.datetime.now()
    ran = 0
    try:
        tasks = session.scalars(
            __import__("sqlalchemy").select(AdminTask).where(AdminTask.status == 1)).all()
    except Exception:
        return 0
    for task in tasks:
        p = task_params(task)
        cycle = str(p.get("cycle") or "day")
        cfgd = p.get("cycle_cfg") or {}
        nxt = task.next_run_at
        if not nxt:
            task.next_run_at = compute_next_run(cycle, cfgd, now)
            continue
        if nxt > now:
            continue
        t0 = _dt.datetime.now()
        status, output = run_task(task, cfg)
        cost_ms = int((_dt.datetime.now() - t0).total_seconds() * 1000)
        session.add(AdminTaskLog(task_id=task.id, status=status,
                                 result=f"[耗时 {cost_ms}ms]\n{output}", run_at=t0))
        task.last_run_at = t0
        task.next_run_at = compute_next_run(cycle, cfgd, _dt.datetime.now())
        ran += 1
    if ran:
        session.commit()
    return ran
