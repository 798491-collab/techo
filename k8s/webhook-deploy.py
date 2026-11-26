#!/usr/bin/env python3
"""Gitee push -> K3s 自动部署接收器。

纯 Python 标准库实现（零第三方依赖），跑在 python:3.10-slim 容器里。
收到合法触发后，通过 nsenter 进入宿主机命名空间执行仓库内的 k8s/k3s-deploy.sh，
复用宿主机的 git / kubectl 环境，容器内无需安装任何工具。
脚本先复制到 /tmp 再运行：部署脚本内部有 git reset --hard，直接跑仓库里的那份
会在发版时覆盖正在执行的脚本自身（bash 边读边执行会错乱）。
"""
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
LOG_FILE = Path("/www/wwwroot/pysite/scripts/webhook.log")
# 在宿主机执行：把仓库脚本复制到临时文件再 bash，避免 git reset 覆盖自身。
# 注意：nsenter 只切换命名空间，子进程仍在本 Pod 的 cgroup 里（内存限额会误伤
# pip/自愈检查）。优先用宿主机 systemd-run 把部署进程放进宿主机自己的 cgroup；
# systemd-run 不可用时回退为直接执行（受 Pod 内存限额约束）。
DEPLOY_SHELL = (
    'run=$(mktemp /tmp/pysite-deploy-XXXXXX.sh) || exit 1; '
    'cp /www/wwwroot/pysite/k8s/k3s-deploy.sh "$run" || exit 1; '
    'if command -v systemd-run >/dev/null 2>&1 && systemd-run '
    '--unit=pysite-deploy-$(date +%s) --collect --quiet '
    '-p StandardOutput=file:/www/wwwroot/pysite/scripts/k3s-deploy.log '
    '-p StandardError=file:/www/wwwroot/pysite/scripts/k3s-deploy.log '
    'bash "$run" 2>/dev/null; then '
    'echo "已通过 systemd-run 在宿主机独立 cgroup 中执行部署"; '
    'else bash "$run"; rm -f "$run"; fi'
)
DEPLOY_CMD = [
    "nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--",
    "bash", "-c", DEPLOY_SHELL,
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "PysiteHook/1.0"

    def _reply(self, code: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/healthz"):
            self._reply(200, "ok")
            return
        self._do_hook()

    def do_POST(self) -> None:
        # 消费请求体，避免连接挂起
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._do_hook()

    def _do_hook(self) -> None:
        if not self.path.startswith("/hook"):
            self._reply(404, "not found")
            return
        # 校验 token（Gitee webhook URL 里带 ?token=xxx）
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        token = ""
        for kv in query.split("&"):
            k, _, v = kv.partition("=")
            if k == "token":
                token = v
        if not TOKEN or token != TOKEN:
            log("拒绝：token 校验失败")
            self._reply(403, "invalid token")
            return
        # 幂等防抖：部署锁存在时（脚本自身 flock）直接排队等待也没必要，直接触发，
        # 重复触发会被 k3s-deploy.sh 内部 flock 串行化
        log("收到合法触发，执行部署脚本")
        try:
            subprocess.Popen(
                DEPLOY_CMD,
                stdout=open(LOG_FILE, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._reply(200, "deploy triggered")
        except Exception as exc:  # noqa: BLE001
            log(f"触发失败：{exc}")
            self._reply(500, f"trigger failed: {exc}")

    def log_message(self, fmt: str, *args) -> None:  # 静默默认访问日志
        pass


if __name__ == "__main__":
    log(f"webhook receiver 启动，端口 8300，token 长度 {len(TOKEN)}")
    ThreadingHTTPServer(("0.0.0.0", 8300), Handler).serve_forever()
