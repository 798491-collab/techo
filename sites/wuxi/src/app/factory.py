"""应用工厂。

启动时扫描每个业务包的 router.py。静态文件由本进程送出，不查数据库。
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import mimetypes
import threading
import time
from contextlib import asynccontextmanager
from ipaddress import ip_address as _ip_address, ip_network as _ip_network
from pathlib import Path

logger = logging.getLogger("pysite")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.core.cache import FileCache
from app.core.perf import PerfStats, ResponseTimeMiddleware
from app.core.database import Database, OperationLog, Setting
from app.core.oplog import OPLOG_IDS, client_ip
from app.core.settings import ADMIN_DIR, THEMES_ROOT, Settings, load_settings
from app.core.state import set_static_version, set_theme
from app.content.service import CODE_VERSION, publish_due, seed_site


class AdminOpLogMiddleware(BaseHTTPMiddleware):
    """后台写操作统一审计：记录 请求体/响应体 摘要 + 真实客户端 IP。

    设计约束（避免破坏流式与内存开销）：
    - 仅处理 /api/admin/* 的 POST/PUT/DELETE/PATCH；
    - multipart 上传与超大请求体（>64KB）不缓存 body；
    - 流式响应（StreamingResponse / SSE / 大文件）不读取响应体，只记状态码；
    - 响应体超过 64KB 同样只记状态码；
    - 登录等含密码字段自动打码。
    """

    MAX_BODY = 65536

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/admin/") or request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return await call_next(request)

        req_snip = ""
        try:
            ctype = request.headers.get("content-type", "")
            clen = int(request.headers.get("content-length", "0") or 0)
            if "multipart/form-data" not in ctype and 0 < clen <= self.MAX_BODY:
                raw = await request.body()
                req_snip = self._redact(path, raw.decode("utf-8", "replace"))[:500]
        except Exception:
            req_snip = ""

        token = OPLOG_IDS.set([])
        status, resp_snip = 500, ""
        try:
            resp = await call_next(request)
            status = resp.status_code
            rcl = resp.headers.get("content-length", "")
            rtype = resp.headers.get("content-type", "")
            is_stream = isinstance(resp, StreamingResponse) or "stream" in rtype or "event-stream" in rtype
            if (not is_stream) and rcl and rcl.isdigit() and int(rcl) <= self.MAX_BODY:
                chunks = []
                async for chunk in resp.body_iterator:  # 只缓冲小响应，随后原样重建
                    chunks.append(chunk)
                raw = b"".join(chunks)
                resp_snip = self._redact(path, raw.decode("utf-8", "replace"))[:1200]
                headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
                resp = Response(content=raw, status_code=status, headers=headers, media_type=rtype or None)
            else:
                resp_snip = "<流式/大响应 未记录正文>"
            return resp
        except Exception as exc:
            status, resp_snip = 500, f"<异常 {type(exc).__name__}>"
            raise
        finally:
            ids = list(OPLOG_IDS.get())
            OPLOG_IDS.reset(token)
            if ids:
                try:
                    self._flush(request, ids, status, req_snip, resp_snip)
                except Exception:
                    pass

    @staticmethod
    def _redact(path: str, text: str) -> str:
        """密码字段打码；登录请求整体不记录请求体。"""
        if path.rstrip("/").endswith("/login"):
            return "<登录请求不记录正文>"
        import re as _re
        return _re.sub(r'("password[^"]*"\s*:\s*")[^"]*"', r'\1***', text)

    def _flush(self, request: Request, ids: list, status: int, req_snip: str, resp_snip: str):
        ip = client_ip(request)
        session = request.app.state.db.session()
        try:
            rows = session.scalars(
                select(OperationLog).where(OperationLog.id.in_(ids))).all()
            for r in rows:
                extra = f" | 请求: {req_snip}" if req_snip else ""
                extra += f" | 响应[{status}]: {resp_snip}" if resp_snip else f" | 响应[{status}]"
                r.detail = ((r.detail or "") + extra)[:2000]
                if ip:
                    r.ip = ip  # 修正反代场景下的真实客户端 IP
            session.commit()
        finally:
            session.close()


class AdminGuardMiddleware:
    """管理后台访问防护（纯 ASGI，注册在最外层）：

    1. IP 黑/白名单：后台「安全设置」可配置，每行一个，支持
       - 精确 IP：172.16.10.111
       - CIDR：172.16.10.0/24（白名单放行所有来源填 0.0.0.0/0 与 ::/0）
       - 通配符：172.16.*
       默认黑名单模式且列表为空（全放行）；白名单模式列表为空时除本机回环外全部拒绝。
    2. 后台访问地址隐藏（admin_path 配置，默认 admin）：
       - 配置为自定义值（如 secret-admin）后，入口变为 /secret-admin（访问即发 Cookie）；
       - /admin 页面与 /api/admin 接口需持有效入口 Cookie，否则一律 404。
    配置每 30 秒刷新一次；改完设置最长 30 秒生效。
    """

    _TTL = 30.0

    def __init__(self, app):
        self.app = app

    # ---------- 配置 ----------
    def _config(self, scope) -> dict | None:
        app = scope.get("app")
        if app is None or not hasattr(app.state, "db"):
            return None
        state = app.state
        now = time.time()
        cached = getattr(state, "_admin_guard", None)
        if cached and now - cached[0] < self._TTL:
            return cached[1]
        conf = None
        try:
            session = state.db.session()
            try:
                rows = session.scalars(select(Setting.key, Setting.value).where(
                    Setting.key.in_(["admin_path", "admin_ip_mode", "admin_ip_rules"]))).all()
                kv = {k: v for k, v in rows}
            finally:
                session.close()
            conf = {
                "admin_path": (kv.get("admin_path") or "admin").strip().strip("/"),
                "mode": (kv.get("admin_ip_mode") or "blacklist").strip(),
                "rules": [ln.strip() for ln in (kv.get("admin_ip_rules") or "").splitlines() if ln.strip()],
            }
        except Exception:
            return cached[1] if cached else None  # 读库失败沿用上次配置（fail-open 保可用）
        state._admin_guard = (now, conf)
        return conf

    # ---------- IP ----------
    @staticmethod
    def _request_ip(scope) -> str:
        for name in (b"x-forwarded-for", b"x-real-ip"):
            for k, v in scope.get("headers") or []:
                if k == name:
                    val = v.decode("latin-1", "replace").split(",")[0].strip()
                    if val:
                        return val
        client = scope.get("client")
        return client[0] if client else ""

    @staticmethod
    def _ip_match(ip: str, pattern: str) -> bool:
        try:
            if any(ch in pattern for ch in "*?"):
                import fnmatch
                return fnmatch.fnmatch(ip, pattern)
            if "/" in pattern:
                return _ip_address(ip) in _ip_network(pattern, strict=False)
            return ip == pattern
        except ValueError:
            return False

    def _ip_verdict(self, ip: str, conf: dict) -> bool | None:
        """True=放行 False=拒绝 None=按默认策略放行。"""
        if not ip:
            return None
        loopback = ip in ("127.0.0.1", "::1")
        rules = conf["rules"]
        if conf["mode"] == "whitelist":
            if loopback:
                return True
            if not rules:
                return False  # 白名单为空=全拒绝（本机除外），防呆见 UI 提示
            return any(self._ip_match(ip, r) for r in rules)
        if rules and any(self._ip_match(ip, r) for r in rules) and not loopback:
            return False
        return None

    # ---------- Cookie ----------
    @staticmethod
    def _gate_token(admin_path: str) -> str:
        import hashlib as _hl
        return _hl.sha256(f"admin-gate:{admin_path}".encode()).hexdigest()[:32]

    @staticmethod
    def _cookie_value(scope, name: str) -> str:
        from starlette.requests import cookie_parser  # noqa: PLC0415
        for k, v in scope.get("headers") or []:
            if k == b"cookie":
                return cookie_parser(v.decode("latin-1")).get(name, "")
        return ""

    # ---------- 主流程 ----------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        conf = self._config(scope)
        if not conf:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        admin_path = conf["admin_path"]
        custom = bool(admin_path) and admin_path != "admin"
        is_entry = False
        if custom and (path == f"/{admin_path}" or path.startswith(f"/{admin_path}/")):
            # 入口路径改写为真实后台路径
            scope = dict(scope)
            scope["path"] = "/admin" + path[len(admin_path):]
            scope["raw_path"] = scope["path"].encode()
            path = scope["path"]
            is_entry = True
        is_admin_page = path == "/admin" or path.startswith("/admin/")
        is_admin_api = path.startswith("/api/admin")
        if not (is_admin_page or is_admin_api):
            await self.app(scope, receive, send)
            return
        # IP 防护
        verdict = self._ip_verdict(self._request_ip(scope), conf)
        if verdict is False:
            resp = JSONResponse({"code": 403, "msg": "当前 IP 不在允许范围内"},
                                status_code=403)
            await resp(scope, receive, send)
            return
        # 入口隐藏（Cookie 门禁）
        if custom:
            token = self._gate_token(admin_path)
            if self._cookie_value(scope, "admin_gate") != token:
                if is_entry:
                    # 首次访问自定义入口：放行并下发 Cookie
                    await self._run_set_cookie(scope, receive, send, token)
                elif is_admin_api:
                    resp = JSONResponse({"code": 404, "msg": "Not Found"}, status_code=404)
                    await resp(scope, receive, send)
                else:
                    resp = Response("Not Found", status_code=404)
                    await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)

    async def _run_set_cookie(self, scope, receive, send, token):
        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("set-cookie",
                               f"admin_gate={token}; Path=/; Max-Age=604800; HttpOnly; SameSite=Lax")
            await send(message)
        await self.app(scope, receive, send_with_cookie)


def _safe_file(base: Path, rel: str) -> Path | None:
    base = base.resolve()
    target = (base / rel).resolve()
    if target != base and not str(target).startswith(str(base) + "\\") and not str(target).startswith(str(base) + "/"):
        return None
    if not target.is_file():
        return None
    return target


def theme_static_dir(cfg: Settings, theme_name: str) -> Path:
    name = theme_name or "default"
    if name != "default":
        candidate = cfg.theme_root / name / "static"
        if candidate.is_dir():
            return candidate
    return cfg.static_dir


def _etag(path: Path) -> str:
    stat = path.stat()
    return f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def _file(request: Request, path: Path, cache_control: str, media_type: str | None = None) -> Response:
    tag = _etag(path)
    headers = {"ETag": tag, "Cache-Control": cache_control}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    media = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    resp = FileResponse(path, media_type=media)
    resp.headers["ETag"] = tag
    resp.headers["Cache-Control"] = cache_control
    return resp


def _load_memory(db: Database) -> tuple[str, str]:
    session = db.session()
    try:
        theme = session.scalar(select(Setting).where(Setting.key == "theme_active"))
        version = session.scalar(select(Setting).where(Setting.key == "static_version"))
        return (theme.value if theme and theme.value else "default"), str(version.value if version and version.value else "1")
    finally:
        session.close()


def mount_package_routers(app: FastAPI) -> None:
    root = Path(__file__).resolve().parent
    modules = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name.startswith("_") or child.name == "core":
            continue
        if not (child / "router.py").is_file():
            continue
        modules.append(importlib.import_module(f"app.{child.name}.router"))
    seen: set[int] = set()
    for mod in modules:
        router = getattr(mod, "router", None)
        if router is None or id(router) in seen:
            continue
        seen.add(id(router))
        app.include_router(router)


def _guard_env_not_tracked(cfg) -> None:
    """安全检查：.env 含 SECRET_KEY，绝不允许被 Git 跟踪；发现即拒绝启动。"""
    import subprocess
    env_file = Path(cfg.root) / ".env"
    if not env_file.is_file():
        return
    try:
        r = subprocess.run(
            ["git", "-C", str(cfg.root), "ls-files", "--", ".env"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            raise RuntimeError(
                "安全检查失败：.env 文件被 Git 跟踪，SECRET_KEY 有泄露风险，拒绝启动。"
                "请在仓库根目录执行 `git rm --cached sites/"
                f"{cfg.key}/.env` 并确认 .gitignore 生效后重试。"
            )
    except FileNotFoundError:
        pass  # 无 git 环境（如容器内直跑）跳过


def create_app(cfg: Settings | None = None, auto_seed: bool = True) -> FastAPI:
    cfg = cfg or load_settings()
    cfg.ensure_dirs()
    _guard_env_not_tracked(cfg)
    # 导入模型模块，保证建表时元数据完整。
    import app.accounts.models  # noqa: F401
    import app.content.models  # noqa: F401
    import app.forms.models  # noqa: F401
    import app.media.models  # noqa: F401

    db = Database(cfg.db_file)
    db.init_schema()
    cache = FileCache(cfg.cache_path, default_ttl=300)
    theme_name, _ = _load_memory(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 新进程启动时清掉上一版本遗留的整页缓存：
        # 磁盘 HTML 与内存 LRU 一起清，避免旧模板渲染结果被回写后继续命中。
        removed = cache.clear_page()
        if removed:
            logger.info("启动清理整页缓存：删除 %d 个旧页面文件（%s）", removed, cfg.cache_path)
        else:
            logger.info("启动清理整页缓存：无旧页面文件（%s）", cfg.cache_path)

        async def publish_loop():
            while True:
                try:
                    session = app.state.db.session()
                    try:
                        publish_due(session)
                    finally:
                        session.close()
                except Exception:
                    pass
                await asyncio.sleep(60)

        async def cron_loop():
            from app.core import jobs as cronjobs
            while True:
                try:
                    session = app.state.db.session()
                    try:
                        cronjobs.run_due_tasks(session, cfg)
                    finally:
                        session.close()
                except Exception:
                    pass
                await asyncio.sleep(60)

        task = asyncio.create_task(publish_loop())
        cron_task = asyncio.create_task(cron_loop())
        # 缩略图缓存过期清理（后台线程，不阻塞启动）：THUMB_CACHE_DAYS 控制，默认 30 天
        def _thumb_gc():
            try:
                from app.media.thumb import cleanup_cache
                removed = cleanup_cache(cfg.cache_path)
                if removed:
                    logger.info("缩略图缓存清理：删除 %d 个过期文件", removed)
            except Exception:
                pass
        threading.Thread(target=_thumb_gc, daemon=True, name="thumb-gc").start()
        yield
        task.cancel()
        cron_task.cancel()

    app = FastAPI(title=cfg.key or "PySite", version="2.0", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        """统一 HTTP 异常为后台 api() 可识别的 {code,msg} 结构。"""
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)
        return JSONResponse(status_code=exc.status_code,
                            content={"code": exc.status_code, "msg": str(detail)}, headers=exc.headers)
    # 后台写操作审计（先注册 = 最内层，看到的是未压缩响应；GZip 在其外层）
    app.add_middleware(AdminOpLogMiddleware)
    # HTML/CSS/JS/JSON 压缩传输（nginx 只压它自己认得的类型，代理响应需要应用层兜底）
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
    # 响应耗时采集（纯 ASGI，开销可忽略）：X-Response-Time 响应头 + 内存滑动窗口
    app.state.perf = PerfStats()
    app.add_middleware(ResponseTimeMiddleware, stats=app.state.perf)
    # 后台访问防护（IP 黑/白名单 + 自定义后台地址）：最后注册 = 最外层，最先执行
    app.add_middleware(AdminGuardMiddleware)
    app.state.cfg = cfg
    app.state.db = db
    app.state.cache = cache
    set_theme(app, theme_name)
    set_static_version(app, CODE_VERSION)

    if auto_seed:
        # 线上数据完全以数据库为准：发版不写种子数据、模型字段、角色权限、
        # 分类统一或任何清理逻辑；只有全新空库才初始化一次。
        session = db.session()
        try:
            seeded = session.scalar(select(Setting).where(Setting.key == "site_seeded"))
            from sqlalchemy import func as _func
            from app.core.database import AdminUser as _AdminUser
            has_admin = session.scalar(select(_func.count()).select_from(_AdminUser)) or 0
            if seeded is None and has_admin == 0:
                seed_site(session, cfg, cfg.root / "storage" / "seed.json")
        finally:
            session.close()

    mount_package_routers(app)

    @app.get("/uploads/{path:path}", include_in_schema=False)
    def uploads(request: Request, path: str):
        target = _safe_file(cfg.uploads_path, path)
        if target is None:
            return Response("Not Found", status_code=404)
        process = request.query_params.get("x-oss-process")
        if process:
            from app.media.thumb import cached_process
            try:
                done = cached_process(cfg.uploads_path, cfg.cache_path, path, process)
            except Exception:
                done = None
            if done is not None:
                cached, media, is_placeholder = done
                if is_placeholder:
                    # 占位图（源图损坏/处理异常）：短缓存，避免占位结果被浏览器长存
                    return _file(request, cached, "public, max-age=300", media)
                return _file(request, cached, "public, max-age=2592000", media)
        # 上传文件名为 uuid 随机生成、内容不变，可安全长缓存（重复访问不再回源验证）
        return _file(request, target, "public, max-age=2592000")

    @app.get("/theme-assets/{path:path}", include_in_schema=False)
    def theme_assets(request: Request, path: str):
        base = theme_static_dir(cfg, request.app.state.theme_name)
        target = _safe_file(base, path)
        if target is None:
            return Response("Not Found", status_code=404)
        return _file(request, target, "public, max-age=31536000, immutable")

    @app.get("/theme-libs/{path:path}", include_in_schema=False)
    def theme_libs(request: Request, path: str):
        target = _safe_file(THEMES_ROOT / "_libs", path)
        if target is None:
            return Response("Not Found", status_code=404)
        return _file(request, target, "public, max-age=31536000, immutable")

    if ADMIN_DIR.is_dir():
        @app.get("/admin", include_in_schema=False)
        async def admin_redirect():
            return RedirectResponse(url="/admin/", status_code=307)

        @app.get("/admin/", include_in_schema=False)
        @app.get("/admin/index.html", include_in_schema=False)
        async def admin_index_page():
            page = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
            page = page.replace("__STATIC_VER__", str(app.state.static_version)).replace("__SITE_NAME__", cfg.name)
            return HTMLResponse(page)

        app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True), name="admin")

    @app.get("/api/health")
    async def health(request: Request):
        t0 = time.perf_counter()
        from app.core.brand import brand_public
        # 站点名以数据库「基础设置 site_name」为准（配置文件不再承载站点内容）
        db_name = ""
        try:
            from sqlalchemy import select as _select
            session = db.session()
            try:
                # 只取 value 列（select 整行实体会把 ORM 对象序列化成 dict，前端标题变 [object Object]）
                db_name = session.scalar(_select(Setting.value).where(Setting.key == "site_name")) or ""
                if db_name and not isinstance(db_name, str):
                    from app.content.service import jloads as _jl
                    _v = _jl(db_name, "")
                    db_name = _v if isinstance(_v, str) else ""
            finally:
                session.close()
        except Exception:
            pass
        return {
            "status": "ok", "site": cfg.key, "name": db_name or cfg.name,
            "brand": brand_public(),
            "response_time_ms": round((time.perf_counter() - t0) * 1000, 2),
            "perf": request.app.state.perf.snapshot(),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        base = theme_static_dir(cfg, app.state.theme_name)
        # 默认 favicon 统一为仓库根目录 logo.svg 同步下来的 img/favicon.svg
        for name in ("img/favicon.svg", "img/favicon.ico", "favicon.ico"):
            if (base / name).is_file():
                return RedirectResponse(url=f"/theme-assets/{name}", status_code=302)
        return Response(status_code=404)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"code": 20002, "msg": "接口不存在"})
        return Response("页面不存在", status_code=404, media_type="text/plain; charset=utf-8")

    return app
