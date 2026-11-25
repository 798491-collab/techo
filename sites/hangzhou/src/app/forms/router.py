"""前台公共 API：留言提交、表单提交、站内搜索、统计。无需登录（表单模型可要求会员登录）。"""
from __future__ import annotations

import hashlib
import hmac
import threading
from datetime import datetime

from fastapi import APIRouter, Request
from sqlalchemy import or_, select

from app.core.database import Content, FormRecord, Member, Message
from app.content.service import jdumps

router = APIRouter(prefix="/api/frontend")


def ok(data=None, msg="ok"):
    return {"code": 0, "msg": msg, "data": data}


def _member_token_secret(app) -> str:
    return str(getattr(app.state.cfg, "secret", "site-cms-secret"))


def sign_member_token(app, member_id: int) -> str:
    """生成会员登录令牌：<id>.<hmac>（会员登录态未启用时预留）。"""
    sig = hmac.new(_member_token_secret(app).encode(), f"member:{member_id}".encode(),
                   hashlib.sha256).hexdigest()[:32]
    return f"{member_id}.{sig}"


def current_member_id(app, request: Request) -> int:
    """从 cookie member_token 解析会员 ID，无效返回 0。"""
    raw = request.cookies.get("member_token") or ""
    try:
        mid, sig = raw.split(".", 1)
        expect = hmac.new(_member_token_secret(app).encode(), f"member:{int(mid)}".encode(),
                          hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(sig, expect):
            return int(mid)
    except (ValueError, AttributeError):
        pass
    return 0


def _notify_form_email(app, form, data: dict):
    """表单提交后按 notify_email 发送 SMTP 通知（后台线程，失败静默，不影响提交响应）。"""

    def _job():
        try:
            from app.core.database import Setting
            session = app.state.db.session()
            try:
                s = {r.key: r.value for r in session.scalars(select(Setting)).all()}
            finally:
                session.close()
            to = str(form.notify_email or "").strip()
            if not to:
                return
            mail_cfg = {
                "host": s.get("smtp_host"), "port": s.get("smtp_port"), "ssl": s.get("smtp_ssl"),
                "username": s.get("smtp_username"), "password": s.get("smtp_password"),
                "sender_name": s.get("smtp_sender_name") or s.get("site_name") or "官网通知",
            }
            if not str(mail_cfg.get("host") or "").strip() or not str(mail_cfg.get("username") or "").strip():
                return  # 未配置邮箱则跳过
            from app.core.mail import send_mail
            lines = "\n".join(f"{k}: {v}" for k, v in (data or {}).items())
            send_mail(mail_cfg, to, f"【{s.get('site_name', '官网')}】新表单提交通知",
                      f"您的网站表单「{form.title or form.code}」收到一条新提交：\n\n{lines}\n\n"
                      f"提交时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                      "请登录管理后台「自定义表单 → 提交记录」查看详情。")
        except Exception:  # noqa: BLE001 —— 通知失败绝不影响提交
            pass

    threading.Thread(target=_job, daemon=True).start()


@router.post("/message")
async def submit_message(request: Request, payload: dict):
    db = request.app.state.db
    session = db.session()
    try:
        msg = Message(name=str(payload.get("name", ""))[:64], phone=str(payload.get("phone", ""))[:32],
                      email=str(payload.get("email", ""))[:128], company=str(payload.get("company", ""))[:128],
                      content=str(payload.get("content", ""))[:5000],
                      ip=request.client.host if request.client else "")
        session.add(msg)
        session.commit()
        return ok(msg.id, "提交成功，我们会尽快与您联系")
    finally:
        session.close()


@router.post("/form/{code}")
async def submit_form(code: str, request: Request, payload: dict):
    db = request.app.state.db
    session = db.session()
    try:
        from app.core.database import FormModel
        form = session.scalar(select(FormModel).where(FormModel.code == code, FormModel.status == 1))
        if not form:
            return {"code": 20002, "msg": "表单不存在或已关闭"}
        # 需求：表单模型开启「是否需要登录」时，必须会员登录后才能提交
        member_id = 0
        if getattr(form, "need_login", 0):
            member_id = current_member_id(request.app, request)
            if not member_id or not session.get(Member, member_id):
                return {"code": 20003, "msg": "该表单需要登录后才能提交"}
        record = FormRecord(form_id=form.id, form_model_id=form.id, member_id=member_id,
                            data=jdumps(payload),
                            ip=request.client.host if request.client else "")
        session.add(record)
        session.commit()
        if form.notify_email:
            _notify_form_email(request.app, form, payload)
        return ok(record.id, "提交成功")
    finally:
        session.close()


@router.get("/search")
async def search(request: Request, keyword: str = "", model: str = "", page: int = 1, size: int = 10):
    if not keyword.strip():
        return ok({"total": 0, "list": []})
    db = request.app.state.db
    session = db.session()
    try:
        stmt = select(Content).where(
            Content.deleted_at.is_(None), Content.status == "publish",
            or_(Content.title.like(f"%{keyword}%"), Content.summary.like(f"%{keyword}%")),
        )
        if model:
            stmt = stmt.where(Content.model == model)
        total = len(session.scalars(stmt).all())
        rows = session.scalars(stmt.order_by(Content.created_at.desc()).offset((page - 1) * size).limit(size)).all()
        return ok({"total": total, "list": [
            {"id": r.id, "title": r.title, "summary": r.summary, "model": r.model,
             "cover": r.cover, "created_at": r.created_at.strftime("%Y-%m-%d")} for r in rows
        ]})
    finally:
        session.close()
