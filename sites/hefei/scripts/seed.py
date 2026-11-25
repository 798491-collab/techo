"""把 storage/seed.json 再导入一次。已有记录不会被覆盖。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.content.service import seed_site
from app.core.database import Database
from app.core.settings import load_settings

cfg = load_settings()
db = Database(cfg.db_file)
db.init_schema()
session = db.session()
try:
    print(seed_site(session, cfg, cfg.root / "storage" / "seed.json"))
finally:
    session.close()
