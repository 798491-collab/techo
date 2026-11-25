"""安全工具：密码哈希（pbkdf2）、登录令牌（HMAC 签名）。无第三方依赖。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2$" + base64.b64encode(salt + dk).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, payload = stored.split("$", 1)
        if scheme != "pbkdf2":
            return False
        raw = base64.b64decode(payload)
        salt, dk = raw[:16], raw[16:]
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(calc, dk)
    except Exception:
        return False


def make_token(secret: str, username: str, hours: int = 720) -> str:
    payload = {"u": username, "exp": int(time.time()) + hours * 3600}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def parse_token(secret: str, token: str) -> str | None:
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("u")
    except Exception:
        return None
