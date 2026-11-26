"""响应耗时采集：轻量 ASGI 中间件 + 滑动窗口统计。

一处采集，三处消费：
  1. 响应头 X-Response-Time —— 浏览器 DevTools / curl / 压测脚本可直接读取
  2. /api/health 的 perf 字段 —— 健康检查同时回报站点响应耗时
  3. /api/admin/dashboard 的 perf 字段 —— 管理后台仪表盘展示

设计要点：
  - 纯 ASGI 中间件，不经 BaseHTTPMiddleware，单例开销 < 0.05ms
  - 环形队列（deque maxlen）固定内存，不随流量增长
  - threading.Lock 只在写入/快照时短暂持有，兼容同步路由线程池
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from starlette.datastructures import MutableHeaders

__all__ = ["PerfStats", "ResponseTimeMiddleware"]


class PerfStats:
    """最近 N 次请求的响应耗时统计（滑动窗口，进程内）。"""

    def __init__(self, capacity: int = 1000, slow_threshold_ms: float = 200.0) -> None:
        self._capacity = capacity
        self._slow_threshold = slow_threshold_ms
        self._lock = threading.Lock()
        self._samples: deque[float] = deque(maxlen=capacity)
        self._slow: deque[tuple[float, str]] = deque(maxlen=10)

    def record(self, ms: float, path: str = "") -> None:
        """记录一次请求耗时（毫秒）。"""
        with self._lock:
            self._samples.append(ms)
            if ms >= self._slow_threshold:
                self._slow.append((round(ms, 1), path))

    def snapshot(self) -> dict[str, Any]:
        """返回当前窗口统计快照。"""
        with self._lock:
            values = sorted(self._samples)
            slow = [{"ms": ms, "path": path} for ms, path in reversed(self._slow)]
        n = len(values)
        if not n:
            return {
                "count": 0, "avg_ms": 0.0, "p50_ms": 0.0,
                "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "slow": [],
            }

        def percentile(frac: float) -> float:
            return round(values[min(n - 1, int(n * frac))], 2)

        return {
            "count": n,
            "avg_ms": round(sum(values) / n, 2),
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
            "p99_ms": percentile(0.99),
            "max_ms": round(values[-1], 2),
            "slow": slow,
        }


class ResponseTimeMiddleware:
    """注入 X-Response-Time 响应头，并把耗时写入 PerfStats。"""

    def __init__(self, app: Any, stats: PerfStats) -> None:
        self.app = app
        self.stats = stats

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        recorded = False

        async def send_with_timing(message: dict) -> None:
            nonlocal recorded
            if message["type"] == "http.response.start" and not recorded:
                ms = (time.perf_counter() - start) * 1000.0
                headers = MutableHeaders(scope=message)
                headers["X-Response-Time"] = f"{ms:.2f}ms"
                self.stats.record(ms, scope.get("path", ""))
                recorded = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            # 异常路径未发出 response.start 时兜底记录，避免统计缺口
            if not recorded:
                self.stats.record((time.perf_counter() - start) * 1000.0,
                                  scope.get("path", "") + " (异常)")
