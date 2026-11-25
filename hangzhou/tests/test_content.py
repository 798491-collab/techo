"""栏目别名和内容模型菜单。"""
from __future__ import annotations

from sqlalchemy import select

from app.core.database import Content, ContentType


def _login(client) -> dict:
    res = client.post("/api/admin/login", json={"username": "admin", "password": "Admin@2026"})
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 0
    return {"Authorization": f"Bearer {body['data']['token']}"}


def test_reserved_slug_is_rejected(client):
    headers = _login(client)
    res = client.post(
        "/api/admin/save/category",
        json={"name": "搜索", "slug": "search", "model": "page", "status": 1},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["code"] != 0


def test_enabled_model_appears_in_content_menu(client):
    headers = _login(client)
    saved = client.post(
        "/api/admin/content-model/save",
        json={"name": "问答", "code": "qa", "icon": "bi-chat", "status": 1},
        headers=headers,
    )
    assert saved.json()["code"] == 0

    menu = client.get("/api/admin/menu", headers=headers).json()["data"]
    names = [item["name"] for group in menu for item in group["items"]]
    assert "问答" in names

    db = client.app.state.db
    session = db.session()
    try:
        session.add(Content(title="只属于问答", model="qa", status="publish"))
        session.add(Content(title="只属于文章", model="article", status="publish"))
        session.commit()
    finally:
        session.close()

    listed = client.get("/api/admin/list/content?model=qa", headers=headers).json()["data"]
    titles = [row["title"] for row in listed["list"]]
    assert "只属于问答" in titles
    assert "只属于文章" not in titles

    session = db.session()
    try:
        row = session.scalars(select(ContentType).where(ContentType.code == "qa")).one()
        row.status = 0
        session.commit()
    finally:
        session.close()
    menu = client.get("/api/admin/menu", headers=headers).json()["data"]
    names = [item["name"] for group in menu for item in group["items"]]
    assert "问答" not in names
