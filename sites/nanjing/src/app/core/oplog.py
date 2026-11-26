"""后台操作日志辅助：真实客户端 IP + 请求级日志收集。

- client_ip：反向代理（nginx）已注入 X-Real-IP / X-Forwarded-For，
  直接取 request.client.host 拿到的是 127.0.0.1 / 内网代理 IP，
  这里优先解析代理头拿到真实客户端 IP。
- OPLOG_IDS / track_log：log_op 写入日志后记录行 id 到请求级上下文，
  AdminOpLogMiddleware（factory.py）在响应返回后据此回填
  响应摘要与真实 IP，实现「响应也记录」。
"""
from contextvars import ContextVar

# 当前请求已写入的操作日志行 id（同一次请求可能写多条）
OPLOG_IDS: ContextVar[list] = ContextVar("oplog_ids", default=[])


def track_log(row_id: int) -> None:
    try:
        OPLOG_IDS.get().append(int(row_id))
    except Exception:
        pass


def client_ip(request) -> str:
    """真实客户端 IP：优先 X-Forwarded-For 首个地址，其次 X-Real-IP，最后直连地址。"""
    try:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
        real = request.headers.get("x-real-ip", "")
        if real.strip():
            return real.strip()
        return request.client.host if request.client else ""
    except Exception:
        return ""
