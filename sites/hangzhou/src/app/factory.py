"""应用工厂。

启动时扫描每个业务包的 router.py。静态文件由本进程送出，不查数据库。
"""
from __future__ import annotations

import asyncio
import importlib
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.core.cache import FileCache
from app.core.perf import PerfStats, ResponseTimeMiddleware
from app.core.database import Database, Setting
from app.core.settings import ADMIN_DIR, THEMES_ROOT, Settings, load_settings
from app.core.state import set_static_version, set_theme
from app.content.service import publish_due, seed_site


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


def _preserve_contact_template(db: Database, cfg: Settings, theme_name: str) -> None:
    """已有「联系我们」栏目如果没填模板，并且主题里有 contact.html，就记下这个模板名。"""
    from app.core.database import Category
    from app.pages.render import template_exists

    session = db.session()
    try:
        row = session.scalar(select(Category).where(Category.slug == "contact", Category.deleted_at.is_(None)))
        if row and not (row.template or "").strip() and template_exists(cfg, theme_name, "contact.html"):
            row.template = "contact.html"
            session.commit()
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


def create_app(cfg: Settings | None = None, auto_seed: bool = True) -> FastAPI:
    cfg = cfg or load_settings()
    cfg.ensure_dirs()
    # 导入模型模块，保证建表时元数据完整。
    import app.accounts.models  # noqa: F401
    import app.content.models  # noqa: F401
    import app.forms.models  # noqa: F401
    import app.media.models  # noqa: F401

    db = Database(cfg.db_file)
    db.init_schema()
    cache = FileCache(cfg.cache_path, default_ttl=300)
    theme_name, static_version = _load_memory(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
        yield
        task.cancel()
        cron_task.cancel()

    app = FastAPI(title=cfg.key or "PySite", version="2.0", lifespan=lifespan)
    # HTML/CSS/JS/JSON 压缩传输（nginx 只压它自己认得的类型，代理响应需要应用层兜底）
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
    # 响应耗时采集（纯 ASGI，开销可忽略）：X-Response-Time 响应头 + 内存滑动窗口
    app.state.perf = PerfStats()
    app.add_middleware(ResponseTimeMiddleware, stats=app.state.perf)
    app.state.cfg = cfg
    app.state.db = db
    app.state.cache = cache
    set_theme(app, theme_name)
    set_static_version(app, static_version)

    if auto_seed:
        session = db.session()
        try:
            seed_site(session, cfg, cfg.root / "storage" / "seed.json")
        finally:
            session.close()
        _preserve_contact_template(db, cfg, app.state.theme_name)
        # 清理废弃字段：site_wechat（微信号文本框已移除，微信相关只保留 wechat_qrcode 上传位）
        session = db.session()
        try:
            from sqlalchemy import delete as _delete
            session.execute(_delete(Setting).where(Setting.key == "site_wechat"))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        # 文章分类统一：一级「新闻资讯」，二级「公司新闻 / 行业新闻」
        session = db.session()
        try:
            from sqlalchemy import select as _sel, update as _upd
            from app.core.database import Category, Content
            cats = session.scalars(_sel(Category).where(
                Category.deleted_at.is_(None), Category.model == "article", Category.pid == 0)).all()
            if cats:
                parent = None
                for nm in ["新闻资讯", "公司动态", "资讯中心", "新闻中心", "行业动态"]:
                    parent = next((c for c in cats if c.name == nm), None)
                    if parent:
                        break
                if parent is None:
                    parent = cats[0]
                if parent.name != "新闻资讯":
                    parent.name = "新闻资讯"
                # 其余一级文章分类全部挂到「新闻资讯」下成为二级
                for c in cats:
                    if c.id != parent.id and c.pid != parent.id:
                        c.pid = parent.id
                def _child(name):
                    return session.scalar(_sel(Category).where(
                        Category.deleted_at.is_(None), Category.pid == parent.id, Category.name == name))
                comp = _child("公司新闻")
                if not comp:
                    comp = Category(name="公司新闻", slug="company-news", model="article", pid=parent.id,
                                    is_nav=1, status=1, site_id=parent.site_id,
                                    content_type_id=parent.content_type_id, sort=1)
                    session.add(comp)
                    session.flush()
                if not _child("行业新闻"):
                    session.add(Category(name="行业新闻", slug="industry-news", model="article", pid=parent.id,
                                         is_nav=1, status=1, site_id=parent.site_id,
                                         content_type_id=parent.content_type_id, sort=2))
                    session.flush()
                # 原直接挂在一级分类下的文章归入「公司新闻」
                session.execute(_upd(Content).where(
                    Content.category_id == parent.id, Content.deleted_at.is_(None)
                ).values(category_id=comp.id))
                # 子分类 slug 去重：与父级或其他分类冲突时改用标准 slug
                _slug_by_name = {"行业新闻": "hangyexinwen", "公司新闻": "gongsixinwen"}
                _taken = set(session.scalars(_sel(Category.slug).where(
                    Category.deleted_at.is_(None), Category.slug != "")).all())
                for _ch in session.scalars(_sel(Category).where(
                        Category.deleted_at.is_(None), Category.pid == parent.id)).all():
                    if _ch.slug and _ch.slug != parent.slug and sum(1 for s in _taken if s == _ch.slug) == 1:
                        continue
                    _std = _slug_by_name.get(_ch.name) or (_ch.name or "cat")
                    _cand, _k = _std, 2
                    while _cand in _taken:
                        _cand = "%s-%d" % (_std, _k); _k += 1
                    _taken.discard(_ch.slug)
                    _ch.slug = _cand
                    _taken.add(_cand)
                session.commit()
        except Exception:
            session.rollback()
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
            done = cached_process(cfg.uploads_path, cfg.cache_path, path, process)
            if done is not None:
                cached, media = done
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
        for name in ("img/favicon.ico", "img/favicon.svg", "favicon.ico"):
            if (base / name).is_file():
                return RedirectResponse(url=f"/theme-assets/{name}", status_code=302)
        return Response(status_code=404)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"code": 20002, "msg": "接口不存在"})
        return Response("页面不存在", status_code=404, media_type="text/plain; charset=utf-8")

    return app
