"""前台地址规则。"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.core.database import Category, Content


def test_about_page_uses_page_template_and_bare_path_is_404(client):
    db = client.app.state.db
    session = db.session()
    try:
        cat = session.scalars(select(Category).where(Category.slug == "about", Category.deleted_at.is_(None))).one()
        cat.model = "page"
        cat.template = ""
        cat.status = 1
        session.commit()
    finally:
        session.close()
    client.app.state.cache.clear()

    missing = client.get("/about")
    assert missing.status_code == 404

    page = client.get("/about.html")
    assert page.status_code == 200
    assert 'data-page-template="page"' in page.text


def test_content_url_uses_id_and_rejects_title_path(client):
    db = client.app.state.db
    session = db.session()
    try:
        news = session.scalars(select(Category).where(Category.slug == "news", Category.deleted_at.is_(None))).one()
        row = session.get(Content, 12)
        if row is None:
            row = Content(id=12, title="原标题", category_id=news.id, model=news.model or "article", status="publish")
            session.add(row)
        else:
            row.title = "原标题"
            row.category_id = news.id
            row.status = "publish"
            row.deleted_at = None
        session.commit()
    finally:
        session.close()
    client.app.state.cache.clear()

    first = client.get("/news/12.html")
    assert first.status_code == 200
    assert "原标题" in first.text

    session = db.session()
    try:
        row = session.get(Content, 12)
        row.title = "资质办理流程"
        session.commit()
    finally:
        session.close()
    client.app.state.cache.clear()

    renamed = client.get("/news/12.html")
    assert renamed.status_code == 200
    assert "资质办理流程" in renamed.text
    assert client.get("/news/资质办理流程").status_code == 404
    assert client.get("/news/12").status_code == 404
    assert client.get("/list/news").status_code == 404
    assert client.get("/article/12").status_code == 404


def test_sitemap_urls_match_resolver(client):
    body = client.get("/sitemap.xml")
    assert body.status_code == 200
    assert "xml" in body.headers["content-type"]
    locs = re.findall(r"<loc>(.*?)</loc>", body.text)
    assert locs
    for loc in locs:
        path = "/" + loc.split("/", 3)[-1] if loc.startswith("http") else loc
        # loc 形如 http://testserver/news.html
        path = "/" + loc.split("://", 1)[-1].split("/", 1)[-1]
        assert path.endswith(".html")
        opened = client.get(path)
        assert opened.status_code == 200, path


def test_theme_assets_do_not_query_database_and_uploads_return_304(client):
    calls = {"n": 0}
    real = client.app.state.db.session

    def wrapped():
        calls["n"] += 1
        return real()

    client.app.state.db.session = wrapped
    client.app.state.theme_name = "default"
    css = client.get("/theme-assets/css/style.css")
    assert css.status_code == 200
    assert "max-age=31536000" in css.headers.get("cache-control", "")
    assert calls["n"] == 0

    client.app.state.theme_name = "shugao"
    other = client.get("/theme-assets/css/style.css")
    assert other.status_code == 200
    assert calls["n"] == 0
    assert other.content != css.content
    client.app.state.db.session = real

    upload = client.app.state.cfg.uploads_path
    upload.mkdir(parents=True, exist_ok=True)
    target = upload / "probe.txt"
    target.write_text("hello", encoding="utf-8")
    first = client.get("/uploads/probe.txt")
    assert first.status_code == 200
    tag = first.headers["etag"]
    second = client.get("/uploads/probe.txt", headers={"If-None-Match": tag})
    assert second.status_code == 304


def test_list_and_home_use_cached_thumbs(client):
    import os
    import re
    from io import BytesIO

    from PIL import Image

    from app.media.thumb import oss

    upload = client.app.state.cfg.uploads_path
    upload.mkdir(parents=True, exist_ok=True)
    src = upload / "cover-big.jpg"
    Image.frombytes("RGB", (2400, 1600), os.urandom(2400 * 1600 * 3)).save(src, "JPEG", quality=90)
    original_size = src.stat().st_size
    assert oss("/theme-assets/img/ph-case1.svg", 282, 170) == "/theme-assets/img/ph-case1.svg"
    assert "w_282,h_170" in oss("/uploads/cover-big.jpg", 282, 170)

    db = client.app.state.db
    session = db.session()
    try:
        news = session.scalars(select(Category).where(Category.slug == "news", Category.deleted_at.is_(None))).one()
        session.add(Content(
            title="缩略图列表项", category_id=news.id, model="article", status="publish",
            cover="/uploads/cover-big.jpg", summary="列表缩略图", is_top=1,
            body='<p><img src="/uploads/cover-big.jpg" alt="原图"></p>',
        ))
        session.add(Content(
            title="缩略图横幅", model="banner", status="publish", cover="/uploads/cover-big.jpg", extra="{}",
        ))
        session.commit()
        item_id = session.scalars(select(Content).where(Content.title == "缩略图列表项")).one().id
    finally:
        session.close()

    previous_theme = client.app.state.theme_name
    client.app.state.theme_name = "zhongtai"
    client.app.state.cache.clear()
    try:
        listing = client.get("/news.html")
        assert listing.status_code == 200
        assert "w_282,h_170" in listing.text
        assert "w_200,h_200" not in listing.text
        assert "/thumbs/" not in listing.text
        assert not list(client.app.state.cfg.cache_path.glob("oss/**/*.webp"))

        home = client.get("/")
        assert home.status_code == 200
        assert "w_1920,h_600" in home.text
        assert "w_386,h_190" in home.text
        assert "w_200,h_200" not in home.text
        assert "/thumbs/" not in home.text

        detail = client.get(f"/news/{item_id}.html")
        assert detail.status_code == 200
        assert 'src="/uploads/cover-big.jpg"' in detail.text

        urls = re.findall(r"/uploads/cover-big\.jpg\?x-oss-process=[^\"'\s>]+", listing.text)
        assert urls
        thumb = client.get(urls[0])
        assert thumb.status_code == 200
        assert thumb.headers["content-type"].startswith("image/webp")
        assert "max-age=2592000" in thumb.headers["cache-control"]
        assert len(thumb.content) < original_size
        assert Image.open(BytesIO(thumb.content)).size == (282, 170)
        assert list(client.app.state.cfg.cache_path.glob("oss/**/*.webp"))
        again = client.get(urls[0], headers={"If-None-Match": thumb.headers["etag"]})
        assert again.status_code == 304
        other = client.get(
            "/uploads/cover-big.jpg",
            params={"x-oss-process": "image/auto-orient,1/resize,m_fill,w_80,h_60/quality,q_80/format,webp"},
        )
        assert other.status_code == 200
        assert Image.open(BytesIO(other.content)).size == (80, 60)
        plain = client.get("/uploads/cover-big.jpg")
        assert plain.status_code == 200
        assert plain.headers["content-type"].startswith("image/jpeg")
    finally:
        client.app.state.theme_name = previous_theme
        client.app.state.cache.clear()
