import sys
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 字节码缓存统一写入 data，不散落在站点根目录
sys.pycache_prefix = str(ROOT / "storage" / "pycache")


# 站点进程入口：转发到 serve.py
runpy.run_path(str(Path(__file__).with_name('serve.py')), run_name='__main__')
