"""维护工具：把各站点上传目录中的真实资料文件登记入库到 media 表。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select

from app.core.settings import SiteConfig
from app.core.database import Database, Media


def import_uploads_to_media(cfg: SiteConfig) -> dict:
    """扫描 uploads 目录，把图片/PDF/Word 等真实文件登记到素材表（幂等，按 md5 判重）。"""
    db = Database(cfg.db_file)
    session = db.session()
    result = {"added": 0, "skipped": 0}
    try:
        for p in sorted(cfg.uploads_path.iterdir()):
            if not p.is_file():
                continue
            raw = p.read_bytes()
            md5 = hashlib.md5(raw).hexdigest()
            if session.scalar(select(Media).where(Media.md5 == md5)):
                result["skipped"] += 1
                continue
            ext = p.suffix.lower().lstrip(".")
            ftype = "image" if ext in {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "bmp"} else \
                    ("video" if ext in {"mp4", "avi", "mov"} else "file")
            session.add(Media(
                filename=p.name, path=f"/uploads/{p.name}", storage_path=str(p),
                file_type=ftype, file_ext=ext, ext=ext, size=len(raw),
                md5=md5, used_count=0,
            ))
            result["added"] += 1
        session.commit()
    finally:
        session.close()
    return result
