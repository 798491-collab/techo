"""前台地址只有一套规则，导航、正文和网站地图都调用这里。"""
from __future__ import annotations

import re

RESERVED_SLUGS = frozenset({"search", "admin", "api", "uploads", "theme-assets", "theme-libs"})
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def valid_slug(slug: str) -> bool:
    return bool(slug) and slug not in RESERVED_SLUGS and SLUG_RE.fullmatch(slug) is not None


def category_url(slug: str) -> str:
    return f"/{slug}.html"


def content_url(slug: str, content_id: int) -> str:
    return f"/{slug}/{int(content_id)}.html"
