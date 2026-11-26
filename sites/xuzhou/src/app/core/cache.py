"""自研异步文件缓存：每个站点独立缓存目录，JSON 文件 + 过期时间。

用于前台查询结果缓存（栏目树、内容列表、详情），后台保存/删除时精准失效。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("pysite")


class FileCache:
    def __init__(self, cache_dir: Path, default_ttl: int = 300):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
        # 前台整页静态缓存（独立目录，clear 时一并清理）
        self.page_dir = self.cache_dir / "pages"
        self.page_dir.mkdir(parents=True, exist_ok=True)
        # 热点整页内存缓存：key -> (原始 HTML, 预压缩 gzip 字节)。
        # 命中时零磁盘 IO、零 gzip CPU —— 单 worker + GIL 下这是最有效的提速点。
        self._page_mem: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._page_mem_max = 96  # 每站约 96 × 27KB ≈ 2.6MB，五站合计 ~13MB

    def _file(self, key: str) -> Path:
        safe = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str) -> Any | None:
        path = self._file(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if payload.get("expire", 0) < time.time():
            # 缓存过期：删除失败（如只读环境）时直接视为未命中，set 会覆盖旧文件
            try:
                path.unlink(missing_ok=True)
            except BaseException:
                pass
            return None
        return payload.get("value")

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        payload = {"expire": time.time() + (ttl if ttl is not None else self.default_ttl), "value": value}
        try:
            self._file(key).write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        except BaseException:
            # 写入失败（只读/沙箱环境）时静默跳过：缓存是加速层，丢失不影响正确性
            pass

    def delete(self, key: str) -> None:
        try:
            self._file(key).unlink(missing_ok=True)
        except BaseException:
            pass

    def clear_prefix(self, prefix: str) -> None:
        """按前缀清理：key 未做可逆编码，因此维护一个索引文件。"""
        index = self.cache_dir / "_keys.json"
        if not index.exists():
            # 兼容旧数据：全量清空
            self.clear()
            return
        try:
            keys = json.loads(index.read_text(encoding="utf-8"))
        except ValueError:
            keys = {}
        for k in [k for k in keys if k.startswith(prefix)]:
            self.delete(k)
            keys.pop(k, None)
        try:
            index.write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")
        except BaseException:
            pass

    def clear(self) -> None:
        for path in self.cache_dir.glob("*.json"):
            try:
                path.unlink(missing_ok=True)
            except BaseException:
                pass
        self.clear_page()

    # ---------- 前台整页静态缓存 ----------
    def _page_file(self, key: str) -> Path:
        safe = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self.page_dir / f"{safe}.html"

    def get_page(self, key: str) -> str | None:
        hit = self._page_mem.get(key)
        if hit is not None:
            self._page_mem.move_to_end(key)
            return hit[0]
        path = self._page_file(key)
        if not path.exists():
            return None
        try:
            html = path.read_text(encoding="utf-8")
        except (ValueError, OSError):
            return None
        self._page_mem_put(key, html)
        return html

    def get_page_payload(self, key: str) -> tuple[str, bytes] | None:
        """返回 (原始 HTML, 预压缩 gzip 字节)；命中内存时零磁盘零压缩。"""
        hit = self._page_mem.get(key)
        if hit is not None:
            self._page_mem.move_to_end(key)
            return hit
        path = self._page_file(key)
        if not path.exists():
            return None
        try:
            html = path.read_text(encoding="utf-8")
        except (ValueError, OSError):
            return None
        self._page_mem_put(key, html)
        return self._page_mem[key]

    def _page_mem_put(self, key: str, html: str) -> None:
        self._page_mem[key] = (html, gzip.compress(html.encode("utf-8"), compresslevel=1))
        self._page_mem.move_to_end(key)
        if len(self._page_mem) > self._page_mem_max:
            self._page_mem.popitem(last=False)

    def set_page(self, key: str, html: str) -> None:
        try:
            self._page_file(key).write_text(html, encoding="utf-8")
        except BaseException:
            pass
        self._page_mem_put(key, html)

    def clear_page(self) -> int:
        """清理整页缓存（内存 LRU + 磁盘 HTML），返回删除的磁盘文件数。"""
        self._page_mem.clear()
        removed = 0
        for path in self.page_dir.glob("*.html"):
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except BaseException:
                pass
        return removed

    def remember(self, key: str, factory: Callable[[], Any], ttl: int | None = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl)
        # 记录 key 索引，支持前缀清理
        index = self.cache_dir / "_keys.json"
        try:
            keys = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
        except ValueError:
            keys = {}
        keys[key] = 1
        try:
            index.write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")
        except BaseException:
            pass
        return value
