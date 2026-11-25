"""把本站最早的管理员密码重置成一个随机密码，并打印出来。"""
from __future__ import annotations

import random
import sqlite3
import string
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.core.security import hash_password
from app.core.settings import load_settings


def generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(random.SystemRandom().choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def main() -> int:
    cfg = load_settings()
    db_path = cfg.db_file
    if not db_path.exists():
        print(f"[错误] 数据库不存在：{db_path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT id, username, nickname FROM admin_user ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            print("[错误] 未找到任何管理员账号。", file=sys.stderr)
            return 1
        uid, username, nickname = row
        new_pwd = generate_password()
        conn.execute(
            "UPDATE admin_user SET password_hash=?, updated_at=? WHERE id=?",
            (hash_password(new_pwd), datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), uid),
        )
        conn.commit()
    finally:
        conn.close()
    print("=" * 52)
    print(f"站点名称：{cfg.name}")
    print(f"管理员账号：{username}" + (f"（{nickname}）" if nickname else ""))
    print(f"新随机密码：{new_pwd}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
