import runpy
from pathlib import Path
raise SystemExit(runpy.run_path(str(Path(__file__).with_name('reset_password.py')), run_name='__main__') or 0)
