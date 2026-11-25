"""SMTP 邮件发送工具（邮箱配置 / 表单留言通知共用）。"""
from __future__ import annotations

import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr


def send_mail(cfg: dict, to: str, subject: str, body: str) -> tuple[bool, str]:
    """按配置发送纯文本邮件。cfg: host/port/ssl/username/password/sender_name。

    返回 (是否成功, 结果说明)。任何异常都被捕获并转为失败说明，绝不抛出。
    """
    host = str(cfg.get("host") or "").strip()
    user = str(cfg.get("username") or "").strip()
    pwd = str(cfg.get("password") or "")
    if not host or not user or not pwd:
        return False, "SMTP 配置不完整（服务器 / 发件邮箱 / 密码均必填）"
    try:
        port = int(cfg.get("port") or (465 if str(cfg.get("ssl", "1")) in ("1", "true", "True") else 25))
    except (TypeError, ValueError):
        port = 465
    use_ssl = str(cfg.get("ssl", "1")) in ("1", "true", "True")
    sender_name = str(cfg.get("sender_name") or user)

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), user))
    msg["To"] = str(to or user)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            try:
                server.starttls(context=ssl.create_default_context())
            except smtplib.SMTPNotSupportedError:
                pass  # 端口 25 明文
        with server:
            server.login(user, pwd)
            server.sendmail(user, [msg["To"]], msg.as_string())
        return True, "发送成功"
    except Exception as e:  # noqa: BLE001 —— 邮件失败不影响主流程
        return False, f"{type(e).__name__}: {e}"
