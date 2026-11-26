"""前台 Jinja2 SSR 渲染引擎：五站共用同一套渲染逻辑与公共组件。

每套主题只需在各自 theme/templates 下提供页面模板，模板可 import 公共宏
（_shared/themes/macros/*.html），实现「组件化 + 不写重复代码」。
"""
from __future__ import annotations

import contextvars
from datetime import datetime

import json
import hashlib
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.settings import THEMES_MACROS, SiteConfig
from app.core.database import Category, Content
from app.content.service import jloads, to_dict
from app.media.thumb import oss

def _pub_visible():
    # 需求（2026-11-24）：未到发布时间的内容前台不显示（publish_at 为空视为已发布）
    return or_(Content.publish_at.is_(None), Content.publish_at <= datetime.now())


PAGE_ROUTES = {
    "": "index.html",
    "index.html": "index.html",
    "about": "about.html",
    "about.html": "about.html",
    "contact": "contact.html",
    "contact.html": "contact.html",
    "list/{slug}": "list.html",
    "detail/{slug}/{item_id}": "detail.html",
    "article/{item_id}": "detail.html",
    "search": "search.html",
}


def theme_templates_dir(cfg: SiteConfig, theme_key: str):
    """主题模板目录：default=站点自带主题目录；其余=_shared/themes/<key>/templates。"""
    from app.core.settings import THEMES_ROOT
    if theme_key and theme_key != "default":
        d = THEMES_ROOT / theme_key / "templates"
        if d.exists():
            return d
    return cfg.templates_dir


def theme_static_dir(cfg: SiteConfig, theme_key: str):
    """主题静态资源目录：default=站点自带；其余=_shared/themes/<key>/static。"""
    from app.core.settings import THEMES_ROOT
    if theme_key and theme_key != "default":
        d = THEMES_ROOT / theme_key / "static"
        if d.exists():
            return d
    return cfg.static_dir


def build_env(cfg: SiteConfig, theme_key: str = "default") -> Environment:
    """模板搜索路径：当前主题优先，公共宏目录兜底。"""
    loader = ChoiceLoader([
        FileSystemLoader(str(theme_templates_dir(cfg, theme_key))),
        FileSystemLoader(str(THEMES_MACROS)),
    ])
    env = Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )
    env.globals["site"] = _site_stub(cfg)
    env.globals["url_category"] = url_category
    env.globals["url_content"] = url_content
    env.globals["oss"] = oss
    return env


def base_context(request: Request, db: Session, cfg: SiteConfig, extra: dict | None = None) -> dict:
    """注入所有页面共用的上下文：栏目树、导航、推荐内容、站点设置。"""
    from app.core.cache import FileCache
    cache: FileCache = request.app.state.cache

    def load_common():
        rows = db.scalars(
            select(Category).where(Category.deleted_at.is_(None), Category.status == 1).order_by(Category.sort)
        ).all()
        slug_of = {int(c.id): (c.slug or "") for c in rows}
        cats = [to_dict(c) for c in rows]
        nav = [c for c in cats if c.get("is_nav")]
        hot = [{"id": c.id, "title": c.title, "model": c.model, "cover": c.cover,
                "summary": c.summary,
                "created_at": ((c.publish_at or c.created_at) or c.created_at).strftime("%Y-%m-%d"),
                "category_slug": slug_of.get(int(c.category_id or 0), "")}
               for c in db.scalars(select(Content).where(
                   Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.is_hot == 1
               ).order_by(func.coalesce(Content.publish_at, Content.created_at).desc()).limit(6)).all()]
        prods = [{"id": c.id, "title": c.title, "category_slug": slug_of.get(int(c.category_id or 0), "")}
                 for c in db.scalars(select(Content).where(
                     Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "product"
                 ).order_by(Content.is_top.desc(), Content.sort, Content.id.desc()).limit(8)).all()]
        return cats, nav, hot, prods

    # 兼容旧缓存结构（升级前 common 为 3 元组）
    _common = cache.remember("common", load_common, ttl=600)
    if len(_common) == 4:
        cats, nav, hot, footer_products = _common
    else:
        cats, nav, hot = _common
        footer_products = []
    # banner 轮播数据（banner 模型已发布内容：标题/副标题/图片），供主题 hero 使用
    banners = []
    try:
        def _load_banners():
            rows = db.scalars(select(Content).where(
                Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "banner"
            ).order_by(Content.sort, Content.id.desc()).limit(8)).all()
            out = []
            for c in rows:
                try:
                    ex = json.loads(c.extra or "{}")
                except (ValueError, TypeError):
                    ex = {}
                out.append({"title": c.title, "subtitle": ex.get("sub_title") or ex.get("subtitle", ""),
                            "image": c.cover or ex.get("image", ""),
                            "link": ex.get("link_url", ""), "target": ex.get("target", "_self")})
            return out
        banners = cache.remember("banners", _load_banners, ttl=300)
    except Exception:
        banners = []
    # 后台覆盖的站点设置
    settings = {}
    try:
        from app.core.database import Setting
        settings = {s.key: jloads(s.value, s.value) for s in db.scalars(select(Setting)).all()}
    except Exception:
        pass

    stat_rows = db.scalars(select(Content).where(
        Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "stat"
    ).order_by(Content.sort, Content.id)).all()
    stats = [{"value": c.title, "label": c.summary or ""} for c in stat_rows]
    settings["theme_active"] = str(getattr(request.app.state, "theme_name", None) or "default")
    settings["static_version"] = str(getattr(request.app.state, "static_version", None) or settings.get("static_version") or "1")

    ctx = {
        "request": request,
        "categories": cats,
        "nav_categories": nav,
        "hot_contents": hot,
        "footer_products": footer_products,
        "banners": banners,
        "settings": settings,
        "theme_key": settings.get("theme_active") or "default",
        "static_ver": str(settings.get("static_version") or "1"),
        "path": request.url.path,
        "query": dict(request.query_params),
    }
    if extra:
        ctx.update(extra)
    # 站点信息全部来自数据库（后台「基础设置 / SEO 配置」维护），配置文件不再承载站点内容
    ctx["site"] = {
        "key": cfg.key,
        "name": settings.get("site_name") or "",
        "short_name": settings.get("site_short_name") or "",
        "tagline": settings.get("site_tagline") or "",
        "city": settings.get("site_city") or "",
        "industry": settings.get("site_industry") or "",
        "phone": settings.get("site_phone") or "",
        "mobile": settings.get("site_mobile") or "",
        "email": settings.get("site_email") or "",
        "contact": settings.get("contact") or "",
        "qq": settings.get("qq") or "",
        "address": settings.get("site_address") or "",
        "icp": settings.get("icp_no") or "",
        "gongan_icp": settings.get("police_no") or "",
        "keywords": settings.get("seo_keywords") or settings.get("site_keywords") or "",
        "description": settings.get("seo_description") or settings.get("site_description") or "",
        "copyright": settings.get("site_copyright") or "",
        "logo": settings.get("site_logo") or "", "wechat": settings.get("site_wechat") or "",
        "nav": [{"name": c.get("name"), "slug": c.get("slug")} for c in nav],
        "slides": banners, "stats": stats,
    }
    return ctx


def render(cfg: SiteConfig, template: str, context: dict) -> HTMLResponse:
    theme_key = (context.get("settings") or {}).get("theme_active") or "default"
    env: Environment = cfg_root_env(cfg, theme_key)
    tpl = env.get_template(template)
    return HTMLResponse(tpl.render(**context))


def cfg_root_env(cfg: SiteConfig, theme_key: str = "default") -> Environment:
    """复用已构建的 Environment（按 站点+主题 缓存，避免每请求重建）。"""
    cache_key = f"{cfg.key}:{theme_key}"
    env = _ENV.get(cache_key)
    if env is None:
        # 修复：原实现只 get 不 set，且 register_env() 从未被调用，
        # 导致每次整页缓存未命中都重建 Environment 并重新编译全部模板。
        env = build_env(cfg, theme_key)
        _ENV[cache_key] = env
    return env


_ENV: dict[str, Environment] = {}


def register_env(cfg: SiteConfig, env: Environment) -> None:
    _ENV[f"{cfg.key}:default"] = env


def _render_page(request: Request, template: str, slug: str = "", item_id: int = 0, keyword: str = "", kind: str = ""):
    cfg: SiteConfig = request.app.state.cfg
    # 延迟创建 DB Session：首页/详情等缓存命中路径完全不需要它，零对象创建。
    # category 分支需先查栏目确定模板，故单独提前创建。
    db = _db(request) if kind == "category" else None
    try:
        cache = request.app.state.cache
        extra: dict = {}
        cat = None
        if kind == "category":
            cat = db.scalar(select(Category).where(Category.slug == slug, Category.deleted_at.is_(None)))
            if cat is None or int(cat.status or 0) != 1:
                from fastapi.responses import Response
                return Response("页面不存在", status_code=404)
            explicit = (cat.template or "").strip()
            if explicit and not explicit.endswith(".html"):
                explicit += ".html"
            theme_now = str(getattr(request.app.state, "theme_name", None) or "default")
            if explicit and template_exists(cfg, theme_now, explicit):
                template = explicit
            elif (cat.model or "") == "page":
                template = "page.html"
            else:
                template = "list.html"
        elif kind == "detail":
            template = "detail.html"
        # 整页静态缓存：页面级 key = 路径 + 排序后的查询串；动态页面跳过。
        # oss2 让写死 200×200 的页面缓存失效，改由各主题按样式尺寸出图。
        qp = request.query_params
        use_page_cache = (not qp.get("guest_book")) and template != "search.html"
        cache_key = "oss34:" + request.url.path + ("?" + urlencode(sorted(qp.multi_items())) if qp else "")
        if use_page_cache:
            hit = cache.get_page_payload(cache_key)
            if hit is not None:
                raw_html, gz_html = hit
                if "gzip" in request.headers.get("accept-encoding", "").lower():
                    from fastapi.responses import Response
                    return Response(content=gz_html, media_type="text/html",
                                    headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
                return HTMLResponse(raw_html)

        # 缓存未命中才创建 DB Session（category 分支已在上方提前创建）
        if db is None:
            db = _db(request)
        # 栏目 slug 映射仅在需要渲染（缓存未命中）时绑定
        _bind_category_slugs(db)

        # 需求：URL 带 get 参数 guest_book 时渲染「在线留言」表单填写页（ajax 提交）
        if qp.get("guest_book"):
            return _render_guestbook(request, cfg, db, cache)

        if template == "index.html":
            def hero():
                return [{"id": c.id, "title": c.title, "cover": c.cover, "summary": c.summary,
                         "created_at": ((c.publish_at or c.created_at) or c.created_at).strftime("%Y-%m-%d")}
                        for c in db.scalars(select(Content).where(
                            Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.is_top == 1
                        ).order_by(func.coalesce(Content.publish_at, Content.created_at).desc()).limit(8)).all()]
            extra["top_contents"] = cache.remember("top", hero, 300)

            # 首页新闻（article 模型，数量上限给足，主题模板按需 [:N] 截取）
            def news():
                return [to_brief(c) for c in db.scalars(select(Content).where(
                    Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "article"
                ).order_by(Content.is_top.desc(), func.coalesce(Content.publish_at, Content.created_at).desc()).limit(12)).all()]
            extra["news_items"] = cache.remember("news_items", news, 300)

            # 首页精选案例（case 模型，主题模板按需 [:N] 截取）
            def cases():
                return [to_brief(c) for c in db.scalars(select(Content).where(
                    Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "case"
                ).order_by(Content.is_top.desc(), func.coalesce(Content.publish_at, Content.created_at).desc()).limit(12)).all()]
            extra["case_items"] = cache.remember("case_items", cases, 300)

            # 首页服务项目（product 模型，主题模板按需 [:N] 截取）
            def products():
                return [to_brief(c) for c in db.scalars(select(Content).where(
                    Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(), Content.model == "product"
                ).order_by(Content.is_top.desc(), func.coalesce(Content.publish_at, Content.created_at).desc()).limit(12)).all()]
            extra["product_items"] = cache.remember("product_items", products, 300)

            # 首页关于我们：取单页「关于我们」(about 栏目) 内容，封面图供 about-img 使用
            def about_page():
                cat = db.scalar(select(Category).where(Category.slug == "about", Category.deleted_at.is_(None)))
                if not cat:
                    return {}
                row = db.scalar(select(Content).where(
                    Content.category_id == cat.id, Content.deleted_at.is_(None), Content.status == "publish", _pub_visible()
                ).order_by(Content.id))
                return to_dict(row) if row else {}
            extra["about_page"] = cache.remember("about_page", about_page, 300)

        if kind == "category" and (cat.model or "") != "page":
            page = max(1, int(request.query_params.get("page", 1)))
            size = 9
            # 需求：父级分类列表需要展示其所有子分类（无限嵌套）下的内容
            def cat_ids(root_id: int) -> list[int]:
                all_cats = db.scalars(select(Category).where(Category.deleted_at.is_(None))).all()
                children: dict[int, list[int]] = {}
                for c in all_cats:
                    children.setdefault(int(c.pid or 0), []).append(int(c.id))
                ids, stack = [root_id], [root_id]
                while stack:
                    for cid in children.get(stack.pop(), []):
                        ids.append(cid)
                        stack.append(cid)
                return list(dict.fromkeys(ids))
            cat_scope = cat_ids(int(cat.id))
            def items():
                stmt = select(Content).where(Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(),
                                             Content.category_id.in_(cat_scope)).order_by(
                    Content.is_top.desc(), func.coalesce(Content.publish_at, Content.created_at).desc())
                total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
                rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
                return total, [to_brief(c) for c in rows]
            # 注意：这里必须用独立变量名，不能覆盖上方的整页 cache_key（oss34:路径），
            # 否则栏目页整页缓存永远写不进去，每次请求都全量渲染（实测 100ms vs 3ms）。
            list_cache_key = f"listv2:{slug}:{page}"
            total, items_list = cache.remember(list_cache_key, items, 300)
            extra.update({"category": to_dict(cat), "items": items_list, "total": total,
                          "page": page, "pages": max(1, (total + size - 1) // size)})

        if kind == "category" and (cat.model or "") == "page":
            page_item = db.scalar(select(Content).where(
                Content.category_id == cat.id, Content.deleted_at.is_(None), Content.status == "publish", _pub_visible()
            ).order_by(Content.id))
            extra.update({
                "page_item": to_dict(page_item) if page_item else {},
                "body_html": (page_item.body or "") if page_item else "",
                "category": to_dict(cat),
            })

        if template == "detail.html":
            content = db.get(Content, item_id)
            if content is None or content.deleted_at is not None or content.status != "publish" \
                    or (content.publish_at is not None and content.publish_at > datetime.now()):
                from fastapi.responses import Response
                return Response("页面不存在", status_code=404)
            cat = db.get(Category, content.category_id)
            if kind == "detail" and (cat is None or cat.slug != slug or cat.deleted_at is not None or int(cat.status or 0) != 1):
                from fastapi.responses import Response
                return Response("页面不存在", status_code=404)
            _item = to_dict(content)
            try:
                _pd = content.publish_at or content.created_at
                if _pd:
                    _item["created_at"] = _pd.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            extra.update({"item": _item, "category": to_dict(cat) if cat else {},
                          "body_html": content.body or ""})
            # 相关内容
            def related():
                stmt = select(Content).where(Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(),
                                             Content.category_id == content.category_id, Content.id != content.id)
                return [to_brief(c) for c in db.scalars(stmt.order_by(func.coalesce(Content.publish_at, Content.created_at).desc()).limit(4)).all()]
            extra["related"] = cache.remember(f"related:{item_id}", related, 300)

        if template == "search.html":
            from sqlalchemy import or_
            stmt = select(Content).where(Content.deleted_at.is_(None), Content.status == "publish", _pub_visible(),
                                         or_(Content.title.like(f"%{keyword}%"), Content.summary.like(f"%{keyword}%"))) if keyword else select(Content).where(Content.id < 0)
            extra["items"] = [to_brief(c) for c in db.scalars(stmt.order_by(func.coalesce(Content.publish_at, Content.created_at).desc()).limit(30)).all()]
            extra["keyword"] = keyword

        ctx = base_context(request, db, cfg, extra)
        # 主题选择：后台主题管理切换（settings.theme_active），default 回落站点自带模板
        theme_key = str(ctx.get("settings", {}).get("theme_active") or "default")
        env = cfg_root_env(cfg, theme_key)
        try:
            tpl = env.get_template(template)
        except Exception:
            from fastapi.responses import Response
            return Response(f"主题缺少模板: {template}", status_code=500)
        html = tpl.render(**ctx)
        # 注入前台动态数据渲染脚本（浏览量/评论数走接口，不影响页面缓存）
        html = html.replace("</body>", "<script>\n(function(){\n  var nodes=document.querySelectorAll('[data-view-count]');\n  if(!nodes.length) return;\n  var id=nodes[0].getAttribute('data-view-count');\n  var url='/api/stats/'+encodeURIComponent(id);\n  fetch(url,{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(d){\n    nodes.forEach(function(n){ n.textContent=(d&&d.view_count)||0; });\n    document.querySelectorAll('[data-comment-count]').forEach(function(n){ n.textContent=(d&&d.comment_count)||0; });\n  }).catch(function(){});\n})();\n</script>" + "</body>")
        if use_page_cache:
            cache.set_page(cache_key, html)
        return HTMLResponse(html)
    finally:
        # 缓存命中路径 db 为 None（延迟创建），无需关闭
        if db is not None:
            db.close()


def _render_guestbook(request: Request, cfg: SiteConfig, db, cache) -> HTMLResponse:
    """留言表单填写页：渲染 guest_book 表单模型的字段，前端 ajax 提交。"""
    from app.core.database import FormModel
    import json as _json

    def load():
        form = db.scalar(select(FormModel).where(FormModel.code == "guest_book", FormModel.status == 1))
        if not form:
            return {}
        try:
            fields = _json.loads(form.fields or "[]")
        except ValueError:
            fields = []
        return {"id": form.id, "name": form.name, "code": form.code,
                "need_login": bool(getattr(form, "need_login", 0)), "fields": fields}

    form = cache.remember("guest_book", load, 300)
    ctx = base_context(request, db, cfg, {"gb_form": form, "page_title": form.get("name") or "在线留言"})
    theme_key = str(ctx.get("settings", {}).get("theme_active") or "default")
    env = cfg_root_env(cfg, theme_key)
    try:
        tpl = env.get_template("guestbook.html")
    except Exception:
        from fastapi.responses import Response
        return Response("主题缺少模板: guestbook.html", status_code=500)
    return HTMLResponse(tpl.render(**ctx))


def to_brief(c: Content) -> dict:
    # 需求（2026-11-24）：前台时间永远显示发布时间（publish_at），无发布时间回落创建时间
    _disp = (c.publish_at or c.created_at)
    return {"id": c.id, "title": c.title, "subtitle": c.subtitle, "model": c.model,
            "cover": c.cover, "summary": c.summary, "tags": c.tags,
            "created_at": _disp.strftime("%Y-%m-%d") if _disp else "",
            "view_count": c.view_count or 0, "is_top": c.is_top, "is_hot": c.is_hot,
            "category_slug": (_cat_slugs.get() or {}).get(int(c.category_id or 0), "")}

_cat_slugs: contextvars.ContextVar = contextvars.ContextVar("cat_slugs", default={})


def _bind_category_slugs(db) -> None:
    rows = db.scalars(select(Category).where(Category.deleted_at.is_(None))).all()
    _cat_slugs.set({int(c.id): (c.slug or "") for c in rows})


def _site_stub(cfg) -> dict:
    """无数据库上下文时的空兜底（模板渲染正常路径都会被 ctx["site"] 覆盖）。"""
    return {
        "key": cfg.key, "name": "", "short_name": "", "tagline": "",
        "city": "", "industry": "", "phone": "", "mobile": "", "email": "",
        "contact": "", "qq": "", "address": "", "icp": "", "gongan_icp": "",
        "keywords": "", "description": "", "copyright": "",
        "logo": "", "wechat": "", "nav": [], "slides": [], "stats": [],
    }


def url_category(slug) -> str:
    from app.pages.resolve import category_url
    if isinstance(slug, dict):
        slug = slug.get("slug") or ""
    elif not isinstance(slug, str):
        slug = getattr(slug, "slug", "") or ""
    return category_url(slug) if slug else "/"


def url_content(item) -> str:
    from app.pages.resolve import content_url
    if item is None:
        return "/"
    if isinstance(item, dict):
        slug = item.get("category_slug") or ""
        cid = item.get("id")
    else:
        slug = getattr(item, "category_slug", "") or ""
        cid = getattr(item, "id", None)
    if not slug or not cid:
        return "/"
    return content_url(slug, int(cid))


def template_exists(cfg, theme_key: str, name: str) -> bool:
    if (theme_templates_dir(cfg, theme_key) / name).is_file():
        return True
    return (THEMES_MACROS / name).is_file()


def _db(request):
    return request.app.state.db.session()


def render_page(request, template, slug="", item_id=0, keyword="", kind=""):
    return _render_page(request, template, slug=slug, item_id=item_id, keyword=keyword, kind=kind)


def content_stats(request, item_id: int):
    from sqlalchemy import func
    from app.core.database import Comment
    db = _db(request)
    try:
        content = db.get(Content, item_id)
        if content is None or content.deleted_at is not None:
            return {"view_count": 0, "comment_count": 0}
        content.view_count = (content.view_count or 0) + 1
        db.commit()
        comment_count = db.scalar(
            select(func.count()).select_from(Comment).where(
                Comment.content_id == item_id,
                Comment.deleted_at.is_(None),
                Comment.status == "pass",
            )
        ) or 0
        return {"view_count": content.view_count, "comment_count": comment_count}
    finally:
        db.close()


def sitemap_xml(request):
    from fastapi.responses import Response
    from app.pages.resolve import category_url, content_url, valid_slug
    cfg = request.app.state.cfg
    db = _db(request)
    try:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme or "http").split(",")[0].strip()
        host = request.headers.get("host", f"127.0.0.1:{cfg.port}")
        base = f"{scheme}://{host}"
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

        def esc(value) -> str:
            return (str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

        def add(loc, lastmod=None):
            lines.append("  <url>")
            lines.append(f"    <loc>{esc(loc)}</loc>")
            if lastmod is not None:
                lines.append(f"    <lastmod>{lastmod.strftime('%Y-%m-%d')}</lastmod>")
            lines.append("  </url>")

        categories = db.scalars(select(Category).where(Category.deleted_at.is_(None), Category.status == 1)).all()
        by_id = {int(c.id): c for c in categories}
        for cat in categories:
            if valid_slug(cat.slug or ""):
                add(base + category_url(cat.slug), cat.updated_at or cat.created_at)
        for row in db.scalars(select(Content).where(Content.deleted_at.is_(None), Content.status == "publish", _pub_visible())).all():
            cat = by_id.get(int(row.category_id or 0))
            if cat and valid_slug(cat.slug or ""):
                add(base + content_url(cat.slug, row.id), row.publish_at or row.updated_at or row.created_at)
        lines.append("</urlset>")
        return Response("\n".join(lines), media_type="application/xml")
    finally:
        db.close()
