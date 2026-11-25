"""本站进程入口。只监听 .env.example 里的端口。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 字节码缓存统一写入 data，不散落在站点根目录
sys.pycache_prefix = str(ROOT / "storage" / "pycache")
sys.path.insert(0, str(ROOT / "src"))

import uvicorn
from app.core.settings import load_settings
from app.factory import create_app


def setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "site.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fh = TimedRotatingFileHandler(str(log_file), when="midnight", backupCount=30, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    return log_file


cfg = load_settings()
_log_file = setup_logging(cfg.log_path)
app = create_app(cfg)
logger = logging.getLogger("pysite")

if __name__ == "__main__":
    logger.info("站点 %s 启动，端口 %s，日志 %s", cfg.key, cfg.port, _log_file)
    print(f"[{cfg.key}] 前台 http://127.0.0.1:{cfg.port}/")
    print(f"[{cfg.key}] 后台 http://127.0.0.1:{cfg.port}/admin/")
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="info", log_config=None)
