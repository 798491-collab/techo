"""独立站点管理脚本（完全自包含，不依赖任何目录外的代码或脚本）。

用法（在本站点目录内执行）：
    python start.py              启动本站点（前台阻塞，Ctrl+C 停止）
    python start.py status       查看运行状态
    python start.py stop         停止本站点
    python start.py --no-open    启动但不自动打开浏览器

Windows 用户可双击同目录下的：start.bat / stop.bat / status.bat
运行日志写入本站点 storage/logs/run.log。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1]      # 本站点目录（本文件在 scripts/ 下）
PID_FILE = SITE_ROOT / ".pid"
LOG_DIR = SITE_ROOT / "storage" / "logs"
VENV_DIR = SITE_ROOT / ".venv"
ADMIN_URL = "http://127.0.0.1:{port}/admin/"

REQUIRED_PKGS = ["fastapi", "uvicorn[standard]", "jinja2", "sqlalchemy", "python-multipart", "httpx", "pillow"]
# 探测这些源的响应时间，用当前网络最快的那个安装。探测失败的源仍留作安装失败后的后备。
MIRROR_CANDIDATES = [
    "https://pypi.org/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.mirrors.ustc.edu.cn/simple",
]

def _load_meta():
    path = SITE_ROOT / ".env.example"
    data = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith('"'):
            value = json.loads(value)
        elif value.isdigit():
            value = int(value)
        data[key.strip()] = value
    return data


META = _load_meta()
KEY = META.get("key", SITE_ROOT.name)
PORT = int(META.get("port", 0))
NAME = META.get("short_name") or META.get("name", KEY)


def _venv_python():
    for cand in (VENV_DIR / "bin" / "python", VENV_DIR / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return None


def python_executable():
    """优先本站自带的 .venv，否则回退到当前解释器。"""
    return _venv_python() or sys.executable


def _deps_ok(py):
    r = subprocess.run(
        [py, "-c", "import fastapi, uvicorn, jinja2, sqlalchemy, multipart, httpx, PIL"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def _ping_mirror(url, timeout=2.5):
    """返回该源的响应秒数。连不上或返回错误时为 None。"""
    req = urllib.request.Request(url if url.endswith("/") else url + "/", headers={"User-Agent": "pip"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(128)
            if getattr(resp, "status", 200) >= 400:
                return None
        return time.perf_counter() - started
    except Exception:
        return None


def rank_mirrors():
    """按当前网络的实际响应速度排序。探测成功的在前，失败的官方源优先垫后。"""
    scores = {}
    with ThreadPoolExecutor(max_workers=len(MIRROR_CANDIDATES)) as pool:
        futures = {pool.submit(_ping_mirror, url): url for url in MIRROR_CANDIDATES}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                scores[url] = fut.result()
            except Exception:
                scores[url] = None
    reached = sorted((seconds, url) for url, seconds in scores.items() if seconds is not None)
    missed = [url for url in MIRROR_CANDIDATES if scores.get(url) is None]
    official = "https://pypi.org/simple"
    missed.sort(key=lambda url: 0 if url == official else 1)
    return reached, missed


def ensure_deps():
    py = python_executable()
    if _deps_ok(py):
        return py
    print("首次运行：正在初始化本站运行环境（创建 .venv 并安装依赖）…")
    if not VENV_DIR.exists():
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
        if r.returncode != 0:
            sys.exit("虚拟环境创建失败，请手动执行: python3 -m venv .venv")
    py = _venv_python() or python_executable()
    print("  正在检测当前网络，选择安装源…")
    reached, missed = rank_mirrors()
    if reached:
        seconds, url = reached[0]
        print(f"  当前网络选用安装源: {url}（响应 {seconds * 1000:.0f} ms）")
    else:
        print("  安装源暂时探测不到，改为逐个尝试。")
    for mirror in [url for _, url in reached] + missed:
        print(f"  安装依赖（源: {mirror}）…")
        r = subprocess.run([py, "-m", "pip", "install", "-q", "-i", mirror] + REQUIRED_PKGS)
        if r.returncode == 0:
            print("  依赖安装完成。")
            return py
    sys.exit("依赖安装失败，请检查网络后重试。")


def port_in_use(port):
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


def health_ok(port, verbose=False):
    """返回 (健康?, 响应耗时毫秒)；verbose=False 时兼容旧调用返回 bool。"""
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            ok = r.status == 200
            ms = (time.perf_counter() - t0) * 1000
            if verbose:
                print(f"  健康检查 /api/health: HTTP {r.status} 响应耗时 {ms:.2f}ms")
            return (ok, ms) if verbose else ok
    except Exception:
        ms = (time.perf_counter() - t0) * 1000
        if verbose:
            print(f"  健康检查 /api/health: 失败 响应耗时 {ms:.2f}ms")
        return (False, ms) if verbose else False


def load_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def save_pid(pid):
    try:
        PID_FILE.write_text(str(pid), encoding="utf-8")
    except Exception:
        pass


def status(verbose=True):
    pid = load_pid()
    in_use = port_in_use(PORT)
    ok = health_ok(PORT, verbose=verbose) if in_use else False
    if isinstance(ok, tuple):
        ok = ok[0]
    state = "运行中" if ok else ("端口占用" if in_use else "未启动")
    if verbose:
        print(f"{KEY:<10} {PORT:<7} {state:<10} {str(pid or '-'):<9} {NAME}")
    return ok


def stop():
    pid = load_pid()
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                os.kill(pid, 15)
            print(f"[停止] {KEY} PID {pid}")
        except Exception as e:
            print(f"[跳过] {KEY} PID {pid} ({e})")
    save_pid(0)
    time.sleep(1)
    status()


def start(open_browser=True):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if port_in_use(PORT):
        if health_ok(PORT):
            print(f"[{KEY}] 端口 {PORT} 已在运行，无需重复启动。")
        else:
            print(f"[{KEY}] 端口 {PORT} 被占用但服务不健康，请先执行: python start.py stop")
        status()
        if open_browser:
            webbrowser.open(ADMIN_URL.format(port=PORT))
        return

    py = ensure_deps()
    log = open(LOG_DIR / "run.log", "w", encoding="utf-8")
    p = subprocess.Popen(
        [py, str(SITE_ROOT / "scripts" / "serve.py")],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(SITE_ROOT),
    )
    save_pid(p.pid)
    print(f"[启动] {KEY:<10} PID {p.pid}  日志: {LOG_DIR / 'run.log'}")

    print("等待服务就绪", end="", flush=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        if health_ok(PORT):
            break
        print(".", end="", flush=True)
        time.sleep(0.5)
    print()
    status()

    print("\n访问地址：")
    print(f"  前台 http://127.0.0.1:{PORT}/")
    print(f"  后台 http://127.0.0.1:{PORT}/admin/  (admin / admin)")
    if open_browser:
        webbrowser.open(ADMIN_URL.format(port=PORT))

    try:
        p.wait()
    except KeyboardInterrupt:
        print("\n正在停止本站点…")
    finally:
        if p.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/F", "/T"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    p.terminate()
            except Exception:
                pass
        log.close()
        save_pid(0)
        print("已停止本站点。")


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    if "stop" in args:
        stop()
    elif "status" in args:
        status()
    else:
        start(open_browser="--no-open" not in args)
