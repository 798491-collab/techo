"""站点应用包。公司名称只出现在配置和数据库里。"""
import sys as _sys
from pathlib import Path as _Path

# 所有 app.* 模块导入前生效：字节码统一写入 storage/pycache，不散落在源码目录
_sys.pycache_prefix = str(_Path(__file__).resolve().parents[2] / "storage" / "pycache")
