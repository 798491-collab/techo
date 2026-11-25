"""当前主题名和静态版本号放在进程内存里。静态请求只读这块内存。"""
from __future__ import annotations


def set_theme(app, name: str) -> None:
    app.state.theme_name = name or "default"


def set_static_version(app, version: str) -> None:
    app.state.static_version = str(version or "1")
