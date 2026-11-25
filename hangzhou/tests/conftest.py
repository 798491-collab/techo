"""验收测试用的临时库，不碰站点自己的 storage/site.db。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="pysite-test-"))
os.environ["PYSITE_DB"] = str(_TMP / "site.db")
os.environ["PYSITE_UPLOAD"] = str(_TMP / "uploads")
os.environ["PYSITE_CACHE"] = str(_TMP / "cache")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_PASSWORD"] = "Admin@2026"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture(scope="session")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c
