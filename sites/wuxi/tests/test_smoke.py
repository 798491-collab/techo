"""站点冒烟测试（零第三方依赖，仅用标准库）。

用法：
    python tests/test_smoke.py                 # 自动读本站点 site.json 的 port
    BASE_URL=http://127.0.0.1:8101 python tests/test_smoke.py

覆盖：健康检查、首页、后台首页（title 动态注入）、网站地图（系统功能动态生成）。
说明：sitemap.xml 由系统按栏目与已发布内容实时生成，不落地静态文件、不是内容模型。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1]
# 字节码缓存统一写入 data，不散落在站点根目录
sys.pycache_prefix = str(SITE_ROOT / "storage" / "pycache")


def base_url() -> str:
    if os.environ.get("BASE_URL"):
        return os.environ["BASE_URL"].rstrip("/")
    port = 8000
    for raw in (SITE_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("port"):
            port = int(raw.split("=", 1)[1].strip())
    return f"http://127.0.0.1:{port}"


def fetch(path: str):
    url = base_url() + path
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def check(name: str, cond: bool, detail: str = "") -> bool:
    flag = "PASS" if cond else "FAIL"
    print(f"[{flag}] {name}" + (f" - {detail}" if detail else ""))
    return cond


def main() -> int:
    print(f"站点冒烟测试: {base_url()}")
    results = []

    code, body, headers = fetch("/api/health")
    ok = code == 200 and '"status":"ok"' in body.replace(" ", "")
    rt = headers.get("X-Response-Time", "-")
    results.append(check("GET /api/health", ok, f"HTTP {code} 响应耗时 {rt}"))

    code, body, _ = fetch("/")
    results.append(check("GET / (首页)", code == 200, f"HTTP {code}"))

    code, body, _ = fetch("/admin/")
    ok = code == 200 and "__SITE_NAME__" not in body and "<title>" in body
    results.append(check("GET /admin/ (title 动态注入)", ok, f"HTTP {code}"))

    code, body, ctype = fetch("/sitemap.xml")
    ok = code == 200 and "<urlset" in body and "<url>" in body
    results.append(check("GET /sitemap.xml (系统功能动态生成)", ok, f"HTTP {code}, URL数={body.count('<url>')}"))

    passed = all(results)
    print("-" * 50)
    print(f"结果: {sum(results)}/{len(results)} 通过")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
