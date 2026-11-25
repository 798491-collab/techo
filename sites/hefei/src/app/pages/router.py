"""前台系统页和内容页。内容地址只有一个解析器。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.pages.render import content_stats, render_page, sitemap_xml
from app.pages.resolve import valid_slug

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_page(request, "index.html")


@router.get("/search.html", response_class=HTMLResponse)
async def search_page(request: Request, keyword: str = ""):
    return render_page(request, "search.html", keyword=keyword)


@router.get("/sitemap.xml")
async def sitemap(request: Request):
    return sitemap_xml(request)


@router.get("/api/stats/{item_id}")
async def stats(request: Request, item_id: int):
    return content_stats(request, item_id)


@router.get("/{slug}.html", response_class=HTMLResponse)
async def category_page(request: Request, slug: str):
    if not valid_slug(slug):
        return Response("页面不存在", status_code=404, media_type="text/plain; charset=utf-8")
    return render_page(request, "", slug=slug, kind="category")


@router.get("/{slug}/{item_id}.html", response_class=HTMLResponse)
async def content_page(request: Request, slug: str, item_id: str):
    if not valid_slug(slug) or not item_id.isdigit():
        return Response("页面不存在", status_code=404, media_type="text/plain; charset=utf-8")
    return render_page(request, "detail.html", slug=slug, item_id=int(item_id), kind="detail")
