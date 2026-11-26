#!/usr/bin/env python3
"""站点压测脚本：同时输出端到端耗时与服务端耗时，零第三方依赖。

服务端耗时取自应用响应头 X-Response-Time（由 app/core/perf.py 中间件注入），
端到端耗时为客户端实测，二者差值约等于网络往返 + 传输时间。

用法：
  python3 scripts/bench.py http://127.0.0.1:8101/
  python3 scripts/bench.py http://127.0.0.1:8101/ -n 200 -c 30
  python3 scripts/bench.py http://127.0.0.1:8101/api/health -n 60 -c 10
  python3 scripts/bench.py "http://127.0.0.1:8101/uploads/a.jpg?x-oss-process=image/format,webp" -n 60 -c 20

参数：
  -n/--requests   总请求数（默认 100）
  -c/--concurrency 并发数（默认 20）
  --gzip          发送 Accept-Encoding: gzip，模拟真实浏览器
  --warmup        预热请求数（默认 0，避免首次处理影响统计）
  --timeout       单请求超时秒数（默认 20）
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import time
import urllib.error
import urllib.request


def _percentile(sorted_values: list[float], frac: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * frac))
    return sorted_values[idx]


def _one(url: str, use_gzip: bool, timeout: float):
    headers = {"Accept-Encoding": "gzip"} if use_gzip else {}
    req = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            wire = resp.read()
            code = resp.status
            raw_srv = resp.headers.get("X-Response-Time", "")
        try:
            srv = float(raw_srv.replace("ms", "").strip())
        except (ValueError, AttributeError):
            srv = None
        if use_gzip and wire[:2] == b"\x1f\x8b":
            try:
                wire = gzip.decompress(wire)
            except OSError:
                pass
        return time.perf_counter() - started, srv, code, len(wire), None
    except Exception as exc:  # noqa: BLE001 - 压测需统计所有失败
        return time.perf_counter() - started, None, 0, 0, str(exc)


def _line(label: str, values: list[float], scale: float = 1000.0) -> str:
    if not values:
        return f"  {label:<12} 无数据"
    ordered = sorted(values)
    return (
        f"  {label:<12} 平均 {sum(ordered) / len(ordered) * scale:7.2f}ms  "
        f"P50 {_percentile(ordered, .50) * scale:7.2f}ms  "
        f"P95 {_percentile(ordered, .95) * scale:7.2f}ms  "
        f"P99 {_percentile(ordered, .99) * scale:7.2f}ms  "
        f"最大 {ordered[-1] * scale:7.2f}ms"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="站点压测（含服务端响应耗时）")
    ap.add_argument("url", help="被测 URL")
    ap.add_argument("-n", "--requests", type=int, default=100)
    ap.add_argument("-c", "--concurrency", type=int, default=20)
    ap.add_argument("--gzip", action="store_true", help="发送 Accept-Encoding: gzip")
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        ap.error("-n 与 -c 必须为正整数")

    print(f"目标: {args.url}")
    print(f"配置: {args.requests} 请求 / {args.concurrency} 并发 / gzip={'开' if args.gzip else '关'}"
          f" / 预热 {args.warmup}")

    for _ in range(args.warmup):
        _one(args.url, args.gzip, args.timeout)

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: _one(args.url, args.gzip, args.timeout),
                                range(args.requests)))
    wall = time.perf_counter() - t0

    end_to_end = [r[0] for r in results]
    server = [r[1] for r in results if r[1] is not None]
    errors = [r[4] for r in results if r[4]]
    codes = {}
    for r in results:
        codes[r[2]] = codes.get(r[2], 0) + 1
    payloads = [r[3] for r in results if r[2] == 200]

    print("\n──────── 结果 ────────")
    print(f"  总耗时       {wall:.2f}s    QPS {args.requests / wall:.0f}")
    print(f"  HTTP 状态    {codes}")
    print(f"  错误数       {len(errors)}" + (f"  例: {errors[0]}" if errors else ""))
    print(_line("端到端耗时", end_to_end))
    print(_line("服务端耗时", server, scale=1.0))
    if payloads:
        print(f"  响应体大小   平均 {sum(payloads) / len(payloads):,.0f} B")
    if server and end_to_end:
        net = max(0.0, sum(end_to_end) / len(end_to_end) - sum(server) / len(server) / 1000.0)
        print(f"  网络+排队    约 {net * 1000:.2f}ms（端到端均值 - 服务端均值）")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
