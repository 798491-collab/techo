"""共用后台 API（全量版）：登录鉴权、仪表盘、通用 CRUD、上传、站群、备份等。

五站共用同一份代码，通过 request.app.state 拿到各自的 db / cache / config。
所有业务表通过 MODEL_REGISTRY 通用 CRUD 驱动，前端零重复代码。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import FileCache
from app.core.settings import ADMIN_DIR, SiteConfig
from app.core.database import (
    MODEL_REGISTRY, AdminPermission, AdminTask, AdminTaskLog, AdminUser, ApiConsumer, Category,
    Content, ContentType, Database, FormModel, FormRecord, Media, Message, OperationLog, Setting,
    Site, SiteVar, Region,
)
from app.core.security import hash_password, make_token, parse_token, verify_password
from app.core.oplog import client_ip
from app.content.service import (
    bump_static_version, create_item, delete_items, get_item, get_password_rule, jloads, log_op,
    paginate, password_valid, seed_site, to_dict, update_item, MENU_DEFS,
    rule_allows, rules_for_user, STATIC_MODEL_CODES, SKIP_CODES,
)

from app.accounts.router import router

MODELS = MODEL_REGISTRY
# 需要默认过滤软删除的资源
SOFT = {name for name, m in MODEL_REGISTRY.items() if hasattr(m, "deleted_at")}


def ctx(request: Request):
    return request.app.state.cfg, request.app.state.db, request.app.state.cache


def current_admin(request: Request) -> str:
    cfg, _, _ = ctx(request)
    _auth = request.headers.get("Authorization", "").strip()
    token = (_auth[7:] if _auth.startswith("Bearer ") else _auth).strip()  # 兼容 Python 3.8（无 str.removeprefix）
    if not token:
        token = request.cookies.get("cms_token", "")
    username = parse_token(cfg.secret, token)
    if not username:
        raise HTTPException(status_code=401, detail={"code": 10001, "msg": "登录已失效"})
    # 账号被禁用后旧 token 立即失效（RBAC 基础校验）
    _, db, _ = ctx(request)
    session = db.session()
    try:
        user = session.scalar(select(AdminUser).where(AdminUser.username == username))
    finally:
        session.close()
    if not user or int(user.status or 0) != 1:
        raise HTTPException(status_code=401, detail={"code": 10001, "msg": "账号已被禁用"})
    return username


def get_db(request: Request):
    _, db, _ = ctx(request)
    session = db.session()
    try:
        yield session
    finally:
        session.close()


def ok(data=None, msg="ok"):
    return {"code": 0, "msg": msg, "data": data}


def fail(msg, code=20001):
    return {"code": code, "msg": msg}


# ---------------- 图形验证码 ----------------
_CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _captcha_svg(code: str) -> str:
    """生成 4 位图形验证码 SVG（干扰线 + 字符旋转，前端直接内嵌渲染）。"""
    import random as _rnd
    w, h = 120, 40
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    parts.append(f'<rect width="{w}" height="{h}" fill="#f5f7fa"/>')
    # 干扰线
    for _ in range(4):
        x1, y1, x2, y2 = _rnd.randint(0, w), _rnd.randint(0, h), _rnd.randint(0, w), _rnd.randint(0, h)
        color = _rnd.choice(["#b0b6bf", "#9aa7c7", "#a8bfb0", "#c7b0a8"])
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1"/>')
    # 干扰点
    for _ in range(30):
        parts.append(f'<circle cx="{_rnd.randint(0, w)}" cy="{_rnd.randint(0, h)}" r="1" fill="#c0c4cc"/>')
    # 字符
    for i, ch in enumerate(code):
        x = 16 + i * 24 + _rnd.randint(-2, 2)
        y = 27 + _rnd.randint(-3, 3)
        rot = _rnd.randint(-22, 22)
        color = _rnd.choice(["#3b6db4", "#4a8a5f", "#a25b4a", "#6a5ba0", "#3a7a8c"])
        parts.append(f'<text x="{x}" y="{y}" font-family="Georgia, serif" font-size="24" font-weight="bold" '
                     f'fill="{color}" text-anchor="middle" transform="rotate({rot} {x} {y})">{ch}</text>')
    parts.append("</svg>")
    return "".join(parts)


@router.get("/captcha")
async def admin_captcha(request: Request):
    """管理后台登录图形验证码：返回 {id, svg, enabled}，5 分钟有效，验证一次即失效。"""
    _, db, cache = ctx(request)
    session = db.session()
    try:
        row = session.scalar(select(Setting).where(Setting.key == "admin_captcha"))
        enabled = str(row.value if row and row.value else "0") not in ("0", "false", "False")
    finally:
        session.close()
    code = "".join(_CAPTCHA_CHARS[secrets.randbelow(len(_CAPTCHA_CHARS))] for _ in range(4))
    cid = uuid.uuid4().hex
    cache.set(f"captcha:{cid}", code, ttl=300)
    return ok({"id": cid, "svg": _captcha_svg(code), "enabled": enabled})


# ---------------- 认证 ----------------
@router.post("/login")
async def login(request: Request, payload: dict):
    cfg, db, cache = ctx(request)
    session = db.session()
    try:
        # 验证码校验：安全设置 admin_captcha 开启时强制（修复：开关开启但登录页无验证码）
        cap_row = session.scalar(select(Setting).where(Setting.key == "admin_captcha"))
        captcha_on = str(cap_row.value if cap_row and cap_row.value else "0") not in ("0", "false", "False")
        if captcha_on:
            cid = str(payload.get("captcha_id") or "")
            ccode = str(payload.get("captcha_code") or "").strip().upper()
            saved = cache.get(f"captcha:{cid}") if cid else None
            if cid:
                cache.delete(f"captcha:{cid}")  # 一次性：无论对错均失效，防重放
            if not saved or str(saved).upper() != ccode:
                return fail("验证码错误或已过期", 20003)
        user = session.scalar(select(AdminUser).where(AdminUser.username == payload.get("username", "")))
        if not user or not verify_password(payload.get("password", ""), user.password_hash):
            return JSONResponse(status_code=200, content={"code": 20001, "msg": "账号或密码错误"})
        if user.status != 1:
            return fail("账号已被禁用", 10002)
        prev_login_at = user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else ""
        prev_login_ip = user.last_login_ip or ""
        # 归档：上次登录 = 本次登录之前的记录（供 /me 显示「上次登录时间」）
        user.prev_login_at = user.last_login_at
        user.prev_login_ip = user.last_login_ip
        user.last_login_at = datetime.now()
        login_ip = client_ip(request)
        user.last_login_ip = login_ip
        session.commit()
        token = make_token(cfg.secret, user.username)
        return ok({"token": token, "username": user.username,
                   "nickname": user.nickname or user.username, "role": user.role,
                   "avatar": user.avatar or "",
                   "rules": rules_for_user(session, user.username),
                   "is_super": int(user.is_super or 0) == 1 or (user.role or "") == "super",
                   "last_login_at": prev_login_at, "last_login_ip": prev_login_ip}, "登录成功")
    finally:
        session.close()


@router.get("/me")
async def me(request: Request, username: str = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    return ok({
        "username": username,
        "nickname": (user.nickname if user else "") or username,
        "avatar": (user.avatar if user else "") or "",
        "role": (user.role if user else "") or "admin",
        "rules": rules_for_user(db, username),
        "is_super": bool(user and (int(user.is_super or 0) == 1 or (user.role or "") == "super")),
        "last_login_at": (user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user and user.last_login_at else ""),
        "last_login_ip": (user.last_login_ip if user else "") or "",
        # 上次登录时间（本次登录之前的那次，非当前登录）
        "prev_login_at": (user.prev_login_at.strftime("%Y-%m-%d %H:%M:%S") if user and user.prev_login_at else ""),
        "prev_login_ip": (user.prev_login_ip if user else "") or "",
    })


@router.post("/logout")
async def logout():
    return ok()


@router.get("/password-rule")
async def password_rule_get(username: str = Depends(current_admin), db: Session = Depends(get_db)):
    """返回当前管理员密码校验规则（正则 + 文案），供前端统一校验。"""
    return ok(get_password_rule(db))


@router.post("/cache/clear")
async def cache_clear(request: Request, username: str = Depends(current_admin), db: Session = Depends(get_db)):
    """清理本站全部缓存，并将静态资源版本号 +1（强制浏览器刷新 JS/CSS）。"""
    cfg, _, cache = ctx(request)
    cache.clear()
    ver = bump_static_version(db)
    from app.core.state import set_static_version
    set_static_version(request.app, ver)
    log_op(db, username, "system", "clear_cache", "", f"清理缓存，静态资源版本 v{ver}",
           client_ip(request))
    return ok({"version": ver}, f"缓存已清理，静态资源版本已更新为 v{ver}")


@router.post("/password")
async def change_password(request: Request, payload: dict, username: str = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if not user or not verify_password(payload.get("old_password", ""), user.password_hash):
        return fail("原密码错误")
    if not password_valid(db, payload.get("new_password", "")):
        return fail(get_password_rule(db)["tip"])
    user.password_hash = hash_password(payload.get("new_password", ""))
    db.commit()
    return ok(msg="密码已修改")


# ---------------- 菜单（动态，含全部定稿菜单） ----------------
MENU = [dict(m) for m in MENU_DEFS]  # 权威数据见 service.MENU_DEFS


# 分组/菜单开关映射：Setting 中对应 key 为 "0" 时隐藏该组菜单
# 值为列表：组内任一开关关闭即隐藏整组（新菜单把会员/订单、表单/评论合并到同一分组）
GROUP_SWITCH = {
    "站群管理": ["menu_station"],
    "会员财务": ["menu_member", "menu_order"],
    "互动表单": ["menu_comment"],
    "开发管理": ["menu_dev"],
}
MENU_SWITCH = {
    "setting-lang": "menu_lang", "setting-lang-package": "menu_lang",
    "setting-sms": "menu_sms", "setting-email": "menu_email",
}


# 权限节点自动补种（幂等）：邮箱配置菜单 / AI 插件 / AI 添加按钮
EXTRA_PERMS = [
    ("邮箱配置", "setting.email", 8, "menu", "bi-envelope-at", 6),
    ("AI插件管理", "ai.plugin", 9, "menu", "bi-robot", 4),
    ("AI添加内容", "ai.add", 3, "button", "bi-robot", 4),
]


def _ensure_perms(session: Session):
    for name, key, pid, typ, icon, sort in EXTRA_PERMS:
        if not session.scalar(select(AdminPermission).where(AdminPermission.key == key)):
            session.add(AdminPermission(name=name, key=key, pid=pid, type=typ, path="", icon=icon, sort=sort, status=1))
    session.commit()


@router.get("/menu")
async def menu(request: Request, username: str = Depends(current_admin)):
    """返回菜单结构：按角色 rules + 系统开关 + 模型状态过滤，越权菜单不下发。"""
    _, db, _ = ctx(request)
    session = db.session()
    try:
        _ensure_perms(session)
        settings = {r.key: r.value for r in session.scalars(select(Setting)).all()}
        rules = rules_for_user(session, username)
        try:
            models_by_code = {r.code: r for r in session.scalars(select(ContentType)).all()}
        except Exception:
            models_by_code = {}
    finally:
        session.close()

    def enabled(key):
        return str(settings.get(key, "1")) not in ("0", "false", "False")

    def allowed(key, group=""):
        return rule_allows(rules, key, group)

    # 需求：所有启用的内容模型都要出现在「内容管理」菜单下（如单页 page）。
    # 动态模型菜单同样受 rules 约束（权限树中可勾选 content-{code}）。
    dynamic_model_items = [
        {"key": f"content-{ct.code}", "name": ct.name, "icon": ct.icon or "bi-file-earmark"}
        for code, ct in sorted(models_by_code.items(), key=lambda x: x[1].id or 0)
        if code and code not in STATIC_MODEL_CODES | SKIP_CODES
        and int(ct.status or 0) and allowed(f"content-{code}", "内容管理")
    ]

    groups: dict[str, list] = {}
    order = []
    for m in MENU:
        g = m["group"]
        # 角色权限：分组键可直接授权整组；否则逐项匹配菜单 key
        if not allowed(m["key"], g):
            continue
        # 分组级开关（值可为字符串或列表；列表中任一开关关闭即隐藏整组）
        gsw = GROUP_SWITCH.get(g)
        if gsw:
            keys = [gsw] if isinstance(gsw, str) else gsw
            if not all(enabled(k) for k in keys):
                continue
        # 菜单级开关
        msw = MENU_SWITCH.get(m["key"])
        if msw and not enabled(msw):
            continue
        item = {k: v for k, v in m.items() if k != "group"}
        # content-{code} 菜单绑定内容模型（只校验启用状态；静态模型名以 MENU 为准，动态模型名跟随模型）
        if m["key"].startswith("content-"):
            code = m["key"][8:]
            ct = models_by_code.get(code)
            if ct is not None:
                if not int(ct.status or 0):
                    continue  # 模型已禁用：对应菜单不显示
                if code not in STATIC_MODEL_CODES:
                    item["name"] = ct.name  # 非静态模型：菜单名跟随模型名
        # 回收站之前插入动态模型菜单
        if m["key"] == "content-recycle" and dynamic_model_items:
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].extend(dynamic_model_items)
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(item)
    # 分组空则不下发，避免空标题出现在侧栏
    visible = [{"name": g, "items": groups[g]} for g in order if groups[g]]
    return ok(visible)


# ---------------- 仪表盘 ----------------
@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    cfg, _, _ = ctx(request)
    def count(model, *conds):
        stmt = select(func.count()).select_from(model)
        for c in conds:
            stmt = stmt.where(c)
        return db.scalar(stmt) or 0
    recent = db.scalars(select(Content).where(Content.deleted_at.is_(None)).order_by(Content.created_at.desc()).limit(5)).all()
    # 留言统计：按表单提交记录（form_record）统计，而非旧 Message 表
    unread_msg = count(FormRecord, FormRecord.is_read == 0)
    publish_c = count(Content, Content.status == "publish", Content.deleted_at.is_(None))
    draft_c = count(Content, Content.status == "draft", Content.deleted_at.is_(None))
    # 按模型统计（模型代码翻译为中文模型名，如 article -> 新闻 / page -> 单页）
    model_stats = {}
    for row in db.execute(select(Content.model, func.count()).where(Content.deleted_at.is_(None)).group_by(Content.model)).all():
        model_stats[row[0]] = row[1]
    try:
        ct_names = {r.code: r.name for r in db.scalars(select(ContentType)).all()}
        model_stats = {ct_names.get(k, k): v for k, v in model_stats.items()}
    except Exception:
        pass
    return ok({
        "perf": request.app.state.perf.snapshot(),
        "site": {"name": cfg.name, "short_name": cfg.short_name, "theme": cfg.theme, "port": cfg.port},
        "stats": {
            "content": count(Content, Content.deleted_at.is_(None)),
            "publish": publish_c, "draft": draft_c,
            "category": count(Category, Category.deleted_at.is_(None)),
            "message": count(FormRecord), "unread": unread_msg,
            "media": count(Media), "form_record": count(FormRecord),
            "member": count(MODEL_REGISTRY["member"]), "order": count(MODEL_REGISTRY["order"]),
            "comment": count(MODEL_REGISTRY["comment"]),
        },
        "model_stats": model_stats,
        "recent": [{"id": c.id, "title": c.title, "model": c.model,
                    "created_at": c.created_at.strftime("%Y-%m-%d %H:%M")} for c in recent],
    })


# ---------------- 健康检查（开发管理） ----------------
@router.get("/health")
async def admin_health(request: Request, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """站点自检：逐项探测 Web / 数据库 / 缓存 / 磁盘 / 主题，任一异常不影响其他项返回。"""
    t0 = time.perf_counter()
    cfg, _, cache = ctx(request)
    checks = []

    def add(name, status, detail, cost=0.0):
        checks.append({"name": name, "status": status, "detail": detail,
                       "cost_ms": round(cost, 2)})

    # 1) Web 服务：能进入本接口即正常，取当前响应耗时
    add("Web 服务", "ok", "ASGI 服务响应正常", (time.perf_counter() - t0) * 1000)

    # 2) 数据库：真实执行一次查询 + 读取库文件大小
    t = time.perf_counter()
    try:
        n_setting = db.scalar(select(func.count()).select_from(Setting)) or 0
        db_file = cfg.db_file
        size_mb = round(db_file.stat().st_size / 1024 / 1024, 2) if db_file.exists() else 0
        add("数据库", "ok", f"SQLite 可读写 · 配置 {n_setting} 项 · 库文件 {size_mb} MB · WAL 模式",
            (time.perf_counter() - t) * 1000)
    except Exception as e:
        add("数据库", "error", f"查询失败：{type(e).__name__}: {e}", (time.perf_counter() - t) * 1000)

    # 3) 缓存：文件数 + 整页内存缓存条数
    t = time.perf_counter()
    try:
        files = sum(1 for _ in cache.cache_dir.glob("*.json"))
        pages = sum(1 for _ in cache.page_dir.glob("*.html"))
        mem = len(getattr(cache, "_page_mem", {}) or {})
        add("文件缓存", "ok", f"数据缓存 {files} 个 · 整页缓存 {pages} 个 · 内存热点 {mem} 条",
            (time.perf_counter() - t) * 1000)
    except Exception as e:
        add("文件缓存", "error", f"缓存目录异常：{type(e).__name__}: {e}", (time.perf_counter() - t) * 1000)

    # 4) 磁盘：剩余不足 1GB 标警告
    t = time.perf_counter()
    try:
        usage = shutil.disk_usage(cfg.root)
        free_gb = round(usage.free / 1024 ** 3, 2)
        total_gb = round(usage.total / 1024 ** 3, 2)
        status = "warn" if free_gb < 1 else "ok"
        add("磁盘空间", status, f"剩余 {free_gb} GB / 共 {total_gb} GB", (time.perf_counter() - t) * 1000)
    except Exception as e:
        add("磁盘空间", "error", f"读取失败：{type(e).__name__}: {e}", (time.perf_counter() - t) * 1000)

    # 5) 主题与静态资源
    t = time.perf_counter()
    theme = str(getattr(request.app.state, "theme_name", None) or cfg.theme or "default")
    try:
        tpl = cfg.theme_root / theme / "templates" / "base.html"
        static = cfg.theme_root / theme / "static"
        status = "ok" if tpl.is_file() and static.is_dir() else "error"
        add("主题资源", status, f"当前主题 {theme} · 模板{'存在' if tpl.is_file() else '缺失'} · 静态目录{'存在' if static.is_dir() else '缺失'}",
            (time.perf_counter() - t) * 1000)
    except Exception as e:
        add("主题资源", "error", f"检查失败：{type(e).__name__}: {e}", (time.perf_counter() - t) * 1000)

    overall = "error" if any(c["status"] == "error" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks) else "ok")
    return ok({
        "status": overall,
        "site": {"name": cfg.name, "key": cfg.key, "theme": theme, "port": cfg.port},
        "checks": checks,
        "perf": request.app.state.perf.snapshot(),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "response_time_ms": round((time.perf_counter() - t0) * 1000, 2),
    })


# ---------------- 菜单 key -> 资源配置 ----------------
RESOURCE_MAP = {
    "station-site": ("site", "站群管理 / 站点列表"),
    "station-region": ("region", "站群管理 / 地区库"),
    "station-sync": ("site_sync_log", "站群管理 / 同步记录"),
    "content-category": ("category", "内容管理 / 分类"),
    "content-article": ("content", "内容管理 / 文章"),
    "content-product": ("content", "内容管理 / 产品"),
    "content-case": ("content", "内容管理 / 案例"),
    "content-banner": ("content", "内容管理 / banner管理"),
    "content-recycle": ("content", "回收站"),
    "media": ("media", "素材库"),
    "member-list": ("member", "会员列表"),
    "member-group": ("member_group", "会员分组"),
    "member-level": ("member_level", "会员等级"),
    "member-balance-log": ("member_balance_log", "余额流水"),
    "member-point-log": ("member_point_log", "积分流水"),
    "order-list": ("order", "订单列表"),
    "order-refund": ("order_refund", "退款记录"),
    "form-model": ("form_model", "表单模型"),
    "form-record": ("form_record", "提交记录"),
    "comment": ("comment", "评论列表"),
    "tool-task": ("admin_task", "定时任务"),
    "tool-task-log": ("admin_task_log", "任务日志"),
    "auth-admin-user": ("admin_user", "管理员列表"),
    "auth-role": ("admin_role", "角色管理"),
    "auth-permission": ("admin_permission", "权限节点"),
    "setting-log": ("operation_log", "操作日志"),
    "setting-lang": ("lang", "多语言管理"),
    "setting-lang-package": ("lang_package", "语言包管理"),
    "dev-content-model": ("content_type", "开发管理 / 内容模型"),
    "dev-openapi": ("api_consumer", "开发管理 / 开放API"),
}

# 每类资源的列 / 筛选 / 表单配置（配置驱动，前端通用渲染）
# 字段元数据：字段名 -> (中文标签, 控件类型)
# 控件类型：text/number/textarea/editor/password/image/select/switch/icon/json/site
FIELD_META = {
    # —— 系统 / 通用 ——
    "id": ("ID", "text"), "created_at": ("创建时间", "text"), "updated_at": ("更新时间", "text"),
    "site_id": ("所属站点", "site"), "source_site_id": ("来源站点", "site"), "site_ids": ("可管理站点", "json"),
    "name": ("名称", "text"), "key": ("标识键", "text"), "code": ("编码", "text"),
    "slug": ("访问别名", "text"), "title": ("标题", "text"), "subtitle": ("副标题", "text"),
    "icon": ("图标", "icon"), "sort": ("排序", "number"), "status": ("状态", "select"),
    "type": ("类型", "select"), "group": ("分组", "text"), "remark": ("备注", "textarea"),
    "description": ("描述", "textarea"), "summary": ("摘要", "textarea"),
    "body": ("正文内容", "editor"), "content": ("内容", "textarea"), "main_content": ("正文内容", "editor"),
    "value": ("配置值", "textarea"), "var_key": ("变量键", "text"), "var_value": ("变量值", "textarea"),
    "data": ("数据", "json"), "fields": ("字段配置", "json"), "config": ("配置信息", "json"),
    "params": ("参数配置", "json"), "result": ("执行结果", "json"), "extra": ("扩展字段", "json"),
    "privilege": ("权限配置", "json"), "privilege_json": ("权限配置", "json"), "rules": ("权限节点", "json"),
    "content_ids": ("内容ID列表", "json"), "sku_spec": ("规格配置", "json"), "sku_info": ("SKU信息", "json"),
    "list_view": ("列表视图配置", "json"), "form_view": ("表单视图配置", "json"),
    # —— 开关型（选择是/否）——
    "is_comment": ("允许评论", "switch"), "is_order": ("允许下单", "switch"),
    "enable_tag": ("启用标签", "switch"), "is_read": ("是否已读", "switch"),
    "is_top": ("是否置顶", "switch"), "is_hot": ("是否热门", "switch"),
    "is_default": ("是否默认", "switch"), "is_master": ("是否主站", "switch"),
    "is_nav": ("是否导航", "switch"), "is_notify": ("是否通知", "switch"),
    "need_login": ("是否需要登录", "switch"),
    "is_super": ("是否超管", "switch"), "inherit_config": ("继承主站配置", "switch"),
    # —— 选择型 ——
    "model": ("内容模型", "select"), "role": ("角色", "select"),
    "render_mode": ("渲染模式", "select"), "pay_status": ("支付状态", "select"),
    "pay_channel": ("支付渠道", "select"), "file_type": ("文件类型", "select"),
    "lang_code": ("语言", "select"), "level": ("层级", "select"),
    "mode": ("同步模式", "select"), "strategy": ("同步策略", "select"),
    # —— 用户 / 会员 ——
    "username": ("账号", "text"), "nickname": ("昵称", "text"), "password_hash": ("登录密码", "password"),
    "avatar": ("头像", "image"), "mobile": ("手机号", "text"), "phone": ("联系电话", "text"),
    "email": ("邮箱", "text"), "company": ("公司", "text"), "contact": ("联系人", "text"),
    "address": ("地址", "text"), "balance": ("余额", "text"), "point": ("积分", "number"),
    "total_consume": ("累计消费", "text"), "reg_ip": ("注册IP", "text"),
    "last_login_at": ("最后登录", "text"), "admin_user": ("操作人", "text"),
    "admin_user_id": ("操作人ID", "text"), "member_id": ("会员ID", "text"),
    # —— 内容 ——
    "category_id": ("所属分类", "category"), "content_type_id": ("内容类型", "content_type"),
    "content_id": ("内容ID", "text"), "tag_id": ("标签ID", "text"), "pid": ("父级分类", "pid_select"),
    "parent_id": ("父级ID", "number"), "cover": ("封面图", "image"), "cover_id": ("封面ID", "text"),
    "album": ("图集", "gallery"),
    "author": ("作者", "text"), "source": ("来源", "text"), "tags": ("标签", "text"),
    "view_count": ("浏览量", "number"), "publish_at": ("发布时间", "text"),
    "seo_title": ("SEO标题", "text"), "seo_keywords": ("SEO关键词", "text"),
    "seo_description": ("SEO描述", "textarea"), "template": ("模板", "text"),
    "keywords": ("关键词", "textarea"),
    # —— 地区 / 站点 ——
    "region_id": ("所属地区", "region"), "province_id": ("省份ID", "text"),
    "city_id": ("城市ID", "text"), "district_id": ("区县ID", "text"),
    "province": ("省份", "text"), "city": ("城市", "text"), "district": ("区县", "text"),
    "detail": ("详细地址", "text"), "domain": ("域名", "text"), "theme": ("主题", "text"),
    "title_template": ("标题模板", "text"), "static_out_dir": ("静态输出目录", "text"),
    "batch_no": ("批次号", "text"), "target_site_count": ("目标站点数", "number"),
    "pinyin": ("拼音", "text"), "logo_id": ("Logo", "image"),
    # —— 文件 ——
    "filename": ("文件名", "text"), "path": ("文件路径", "text"), "storage_path": ("存储路径", "text"),
    "size": ("大小", "text"), "ext": ("扩展名", "text"), "file_ext": ("扩展名", "text"),
    "mime": ("MIME类型", "text"), "mime_type": ("MIME类型", "text"),
    "width": ("宽度", "number"), "height": ("高度", "number"), "used_count": ("引用次数", "number"),
    "folder": ("文件夹", "text"), "url": ("链接地址", "text"),
    # —— 任务 / 日志 ——
    "task_key": ("任务标识", "text"), "cron": ("Cron表达式", "text"),
    "task_id": ("任务ID", "text"), "last_run_at": ("上次执行", "text"), "next_run_at": ("下次执行", "text"),
    "run_at": ("执行时间", "text"), "ip": ("IP地址", "text"), "user_agent": ("User-Agent", "text"),
    "module": ("所属模块", "text"), "action": ("操作动作", "text"), "target": ("操作对象", "text"),
    # —— 会员等级 / 订单 ——
    "discount": ("折扣", "number"), "point_rate": ("积分倍率", "text"), "min_point": ("积分门槛", "number"),
    "order_no": ("订单号", "text"), "amount": ("订单金额", "text"), "pay_amount": ("实付金额", "text"),
    "pay_time": ("支付时间", "text"), "pay_no": ("支付流水号", "text"),
    "refund_no": ("退款单号", "text"), "refund_amount": ("退款金额", "text"), "reason": ("原因", "textarea"),
    "audit_admin_id": ("审核人", "text"), "audit_at": ("审核时间", "text"), "success_at": ("完成时间", "text"),
    "sku_name": ("SKU名称", "text"), "stock": ("库存", "number"), "price": ("价格", "text"),
    "original_price": ("原价", "text"), "image_id": ("图片ID", "text"), "sku_id": ("SKU_ID", "text"),
    "num": ("数量", "number"), "subtotal": ("小计", "text"),
    "before_balance": ("变动前余额", "text"), "after_balance": ("变动后余额", "text"),
    "before_point": ("变动前积分", "number"), "after_point": ("变动后积分", "number"),
    "before_stock": ("变动前库存", "number"), "after_stock": ("变动后库存", "number"),
    "related_no": ("关联单号", "text"), "notify_email": ("通知邮箱", "text"),
    "form_model_id": ("表单模型", "text"), "form_id": ("表单ID", "text"),
    "field_key": ("字段键", "text"), "field_value": ("字段值", "textarea"),
    "read_at": ("阅读时间", "text"),
    # —— 开放API / 定时任务 ——
    "app_key": ("AppKey", "text"), "app_secret": ("AppSecret", "text"),
    "total_calls": ("总调用次数", "number"), "today_calls": ("今日调用", "number"),
}

# 各选择型字段的选项
STATUS_OPTIONS = [
    {"value": "publish", "label": "已发布"}, {"value": "draft", "label": "草稿"}, {"value": "hidden", "label": "隐藏"},
]
ENABLE_OPTIONS = [{"value": "1", "label": "启用"}, {"value": "0", "label": "停用"}]
BOOL_OPTIONS = [{"value": "1", "label": "是"}, {"value": "0", "label": "否"}]
MODEL_OPTIONS = [
    {"value": "article", "label": "文章"}, {"value": "product", "label": "产品"},
    {"value": "case", "label": "案例"}, {"value": "page", "label": "单页"},
    {"value": "banner", "label": "banner管理"},
]
ROLE_OPTIONS = [
    {"value": "super", "label": "超级管理员"}, {"value": "admin", "label": "管理员"}, {"value": "editor", "label": "编辑"},
]
RENDER_OPTIONS = [
    {"value": "dynamic", "label": "动态渲染"}, {"value": "pseudo_static", "label": "伪静态"}, {"value": "static", "label": "纯静态"},
]
PAY_STATUS_OPTIONS = [
    {"value": "unpaid", "label": "未支付"}, {"value": "paid", "label": "已支付"}, {"value": "refunded", "label": "已退款"},
]
SELECT_OPTIONS = {
    "status": ENABLE_OPTIONS, "role": ROLE_OPTIONS, "model": MODEL_OPTIONS,
    "render_mode": RENDER_OPTIONS, "pay_status": PAY_STATUS_OPTIONS,
    "file_type": [{"value": "image", "label": "图片"}, {"value": "video", "label": "视频"}, {"value": "file", "label": "文件"}],
    "lang_code": [{"value": "zh-CN", "label": "简体中文"}, {"value": "en", "label": "English"}],
    "level": [{"value": "province", "label": "省"}, {"value": "city", "label": "市"}, {"value": "district", "label": "区/县"}],
    "mode": [{"value": "content", "label": "内容"}, {"value": "config", "label": "配置"}, {"value": "seo", "label": "SEO"}],
    "strategy": [{"value": "skip", "label": "跳过重复"}, {"value": "overwrite", "label": "覆盖"}],
    "pay_channel": [{"value": "wechat", "label": "微信支付"}, {"value": "alipay", "label": "支付宝"}, {"value": "offline", "label": "线下支付"}],
    "type": [{"value": "menu", "label": "菜单"}, {"value": "button", "label": "按钮"}, {"value": "api", "label": "接口"}],
}


def cat_tree_options(cats: list, model: str | None = None, top_label: str = "不选择") -> list:
    """把分类列表构建成带缩进层次的树形下拉选项；可按内容模型过滤（分类无限嵌套）。"""
    items = [c for c in cats if (model is None or c.get("model") == model)]
    by_pid: dict[int, list] = {}
    for c in items:
        by_pid.setdefault(int(c.get("pid") or 0), []).append(c)

    def walk(pid: int, depth: int, out: list):
        for c in sorted(by_pid.get(pid, []), key=lambda x: (x.get("sort") or 0, int(x["value"]))):
            out.append({"value": c["value"], "label": ("　" * depth) + ("├─ " if depth else "") + c["label"]})
            walk(int(c["value"]), depth + 1, out)

    out: list = []
    walk(0, 0, out)
    # 需求：所属分类下拉去掉无意义的「— 请选择分类 —」占位项（top_label=None 时不输出）
    if top_label is not None:
        out = [{"value": "0", "label": top_label}] + out
    return out


# 需求（2026-11-24）：内容按模型强制必填 —— 文章/项目/案例 分类+正文必填；页面 正文必填；banner 封面图必传
CONTENT_REQUIRED_BY_MODEL = {
    "article": ("category_id", "body"),
    "product": ("category_id", "body"),
    "case": ("category_id", "body"),
    "page": ("body",),
    "banner": ("cover",),
}


def _force_model_required(form: list, force_model: str | None):
    for k in CONTENT_REQUIRED_BY_MODEL.get(force_model or "", ()):
        for f in form:
            if f.get("key") == k:
                f["required"] = True


def build_config(resource: str, title: str = "", force_model: str | None = None, readonly=False,
                 site_options=None, category_options=None, content_type_options=None, region_options=None,
                 enabled_model_options=None, model_extra_fields: list | None = None) -> dict:
    model = MODELS.get(resource)
    if model is None:
        return {}
    cols = [c.name for c in model.__table__.columns]
    site_options = site_options or []
    category_options = category_options or []
    content_type_options = content_type_options or []
    region_options = region_options or []
    # 选择展示列：优先常见字段，最多 8 列
    preferred = ["id", "title", "name", "username", "code", "slug", "model", "filename", "phone", "mobile",
                 "status", "pay_status", "is_read", "sort", "size", "used_count", "created_at"]
    # 内容列表：封面图优先展示
    if resource == "content":
        preferred = ["id", "cover", "title", "category_id", "model", "status", "author", "publish_at", "created_at"]
    # 表单提交记录：表单类型 + 提交内容
    if resource == "form_record":
        preferred = ["id", "form_type", "data", "member_id", "is_read", "ip", "created_at"]
    # 素材库：增加 素材类型 / 上传人 两列（uploader 为虚拟列，由 list 接口回填）
    if resource == "media":
        preferred = ["id", "filename", "file_type", "uploader", "size", "used_count", "created_at"]
    # 开放API：展示 名称/AppKey/AppSecret/调用量/状态
    if resource == "api_consumer":
        preferred = ["id", "name", "app_key", "app_secret", "total_calls", "today_calls", "status", "remark", "created_at"]
    # 操作日志：增加 操作人 列
    if resource == "operation_log":
        preferred = ["id", "module", "action", "target", "admin_user", "ip", "created_at"]
    virtual_cols = {"form_type", "category_name", "uploader"}
    show_cols = [c for c in preferred if c in cols or c in virtual_cols][:8]
    if "id" not in show_cols:
        show_cols.insert(0, "id")
    column_labels = {"form_type": "表单名称", "category_name": "所属栏目",
                     "file_type": "素材类型", "uploader": "上传人", "admin_user": "操作人"}
    if resource == "form_record":
        column_labels["data"] = "提交内容"
    columns = [{"key": c, "label": column_labels.get(c, FIELD_META.get(c, (c, "text"))[0])} for c in show_cols]
    filters = [{"key": "keyword", "label": "关键词", "type": "text"}]
    if "model" in cols:
        # 需求：所有展示内容模型的地方用模型名称（来自内容模型表），不写死标识
        filters.append({"key": "model", "label": "内容模型", "type": "select",
                        "options": enabled_model_options or MODEL_OPTIONS})
    if "status" in cols:
        st = STATUS_OPTIONS if resource in {"content"} else ENABLE_OPTIONS
        filters.append({"key": "status", "label": "状态", "type": "select", "options": st})
    form = []
    # V16：内容模型字段定义驱动表单与列表列（含系统字段；顺序/隐藏/label/必填 以字段管理配置为准）
    if resource == "content" and force_model and model_extra_fields:
        model_fields = model_extra_fields
        # —— 列表列：list=1 且非 hidden 的字段（系统字段用列名；扩展字段展开为 x_*，由 list 接口回填）——
        col_keys = []
        for fd in model_fields:
            if fd.get("hidden") or not fd.get("list"):
                continue
            n = fd["name"]
            if fd.get("sys") and n in SYS_FORM_TYPES:
                col_keys.append("category_name" if n == "category_id" else n)
            elif not fd.get("sys"):
                col_keys.append("x_" + n)
        col_keys = [c for c in col_keys if c in cols or c == "category_name" or c.startswith("x_")][:9]
        columns = [{"key": "id", "label": "ID"}] + [
            {"key": c, "label": column_labels.get(c, FIELD_META.get(c, (c, "text"))[0])} for c in col_keys]
        for fd in model_fields:
            if not fd.get("sys") and not fd.get("hidden") and fd.get("list"):
                for col in columns:
                    if col["key"] == "x_" + fd["name"]:
                        col["label"] = fd.get("label") or fd["name"]
        # —— 表单：严格按字段定义顺序渲染；hidden=1 的字段在表单中不显示 ——
        for fd in model_fields:
            if fd.get("hidden"):
                continue
            n = fd["name"]
            if fd.get("sys") and n in SYS_FORM_TYPES:
                field = {"key": n, "label": fd.get("label") or SYS_FIELD_MAP[n][0],
                         "type": SYS_FORM_TYPES[n], "sys": True}
                if n == "title":
                    field["full"] = True
                if n == "status":
                    field["options"] = STATUS_OPTIONS
                elif n == "category_id":
                    field["options"] = cat_tree_options(category_options, force_model, None)
                elif n in ("is_top", "is_hot"):
                    field["options"] = BOOL_OPTIONS
                elif n == "cover":
                    field["ratio"] = "16:9"  # 封面图上传区：推荐比例 16:9
                elif n == "publish_at":
                    field["value"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if fd.get("required"):
                    field["required"] = True
                form.append(field)
                # 产品/案例保留图集（存 extra JSON），紧跟封面图之后
                if n == "cover" and force_model in ("product", "case"):
                    form.append({"key": "album", "label": "图集", "type": "image_multi"})
            elif not fd.get("sys"):
                _ft = fd.get("type")
                _ft = FIELD_TYPE_ALIAS.get(_ft, _ft)  # 旧类型映射（image/file/gallery）
                field = {"key": "extra." + n, "label": fd.get("label") or n,
                         "type": _ft if _ft in FIELD_TYPE_OPTIONS else "text",
                         "value": fd.get("default", ""), "_extra": True}
                if field["type"] in ("select", "radio", "checkbox") and fd.get("options"):
                    field["options"] = fd["options"]
                if field["type"] == "selectpage" and fd.get("rel_model"):
                    field["rel_model"] = fd["rel_model"]
                if fd.get("required"):
                    field["required"] = True
                form.append(field)
        if force_model:
            form.insert(0, {"key": "model", "label": "内容模型", "type": "hidden", "value": force_model})
        _force_model_required(form, force_model)
        return {"title": title or resource, "model": resource, "columns": columns,
                "filters": filters, "form": form, "readonly": readonly, "size": 10}
    # 需求：所有 CRUD 表单移除「所属站点」；管理员新增不显示最后登录时间
    skip = {"id", "created_at", "updated_at", "deleted_at", "deleted_by",
            "site_id", "source_site_id"}
    if resource == "admin_user":
        # 需求（2026-11-24）：管理员添加/编辑不显示 last_login_ip / prev_login_ip / prev_login_at
        skip |= {"last_login_at", "last_login_ip", "prev_login_ip", "prev_login_at"}
    if resource == "content_type":
        skip.add("enable_tag")  # 需求：删除所有标签功能
    if resource == "category":
        # 需求：分类管理去掉 内容类型/封面ID/权限配置/模板/是否导航；父级改为下拉选择（树形）
        skip |= {"content_type_id", "cover_id", "cover", "privilege_json", "template", "is_nav"}
    if resource == "admin_role":
        # 需求：角色权限节点可视化选择；删除「可管理站点」
        skip.add("site_ids")
    if resource == "media":
        # 需求：素材库不要「文件夹」字段；表单精简为 文件名/文件/类型/大小
        skip |= {"folder", "storage_path", "ext", "file_ext", "mime", "mime_type",
                 "width", "height", "used_count", "md5", "url"}
    if resource == "api_consumer":
        # 需求：开放API 页面完全复用通用 CRUD；表单只留 名称/备注/状态，密钥与统计在列表展示
        skip |= {"app_key", "app_secret", "total_calls", "today_calls", "today_date"}
    if resource == "admin_task":
        # 需求：定时任务也用通用 CRUD 页面；执行时间为系统自动维护
        skip |= {"last_run_at", "next_run_at"}
    # 需求：内容表单精简 —— 去掉内容类型/副标题/封面ID/作者/来源/扩展字段/标签/摘要
    # 访问别名(slug)保留：用户不填时后端自动按标题拼音/原文生成
    # 正文只保留一个编辑框；作者/摘要由后端自动生成
    content_skip = {"content_type_id", "subtitle", "cover_id", "author", "source",
                    "extra", "tags", "summary", "main_content", "site_id", "view_count"}
    # 需求（2026-11-23）：除「页面」外，内容表单不再显示访问别名（保存时后端按标题自动生成 slug）
    if resource == "content" and force_model != "page":
        content_skip.add("slug")
    # 必填字段（供前端 JustValidate 标红星 + 校验）
    required_fields = {
        "title", "name", "username", "code", "body", "content",
        # 需求（2026-11-24）：管理员 账号/密码/昵称/头像/角色/状态 必填；角色 名称/权限节点/状态 必选
        "nickname", "avatar", "role", "status", "rules",
    }
    for c in cols:
        if c in skip:
            continue
        if resource == "content" and c in content_skip:
            continue
        label, typ = FIELD_META.get(c, (c, "text"))
        if force_model and c == "model":
            form.append({"key": "model", "label": "内容模型", "type": "hidden", "value": force_model})
            continue
        # 正文用一个富文本编辑框：content 的 body 用 editor
        if resource == "content" and c == "body":
            typ = "editor"
        field = {"key": c, "label": label, "type": typ}
        if c in required_fields:
            field["required"] = True
        # 状态按资源区分：内容用发布状态，其余用启用/停用
        if c == "status" and resource == "content":
            field["options"] = STATUS_OPTIONS
        elif c == "rules" and resource == "admin_role":
            field["type"] = "perm_tree"   # 权限节点可视化选择
        elif c == "pid" and resource == "category":
            field["type"] = "select"
            field["options"] = cat_tree_options(category_options, None, "— 顶级分类 —")
        elif c in SELECT_OPTIONS:
            # 需求：分类管理的内容模型下拉动态取「内容模型表」中启用的模型，不写死
            if c == "model" and resource == "category" and enabled_model_options:
                field["options"] = enabled_model_options
            else:
                field["options"] = SELECT_OPTIONS[c]
        elif c == "task_key" and resource == "admin_task":
            # 定时任务类型下拉（对标宝塔任务类型）
            from app.core import jobs as _cronjobs
            field["type"] = "select"
            field["options"] = [{"value": k, "label": v} for k, v in _cronjobs.TASK_TYPES.items()]
        # 外键型字段：动态注入选项
        elif c in ("site_id", "source_site_id"):
            field["type"] = "select"
            field["options"] = [{"value": "0", "label": "本站"}] + site_options
        elif c == "category_id":
            field["type"] = "select"
            # 需求：所属分类只显示与内容模型匹配的分类（如公司动态→article）
            field["options"] = cat_tree_options(category_options, force_model, None)
        elif c == "content_type_id":
            field["type"] = "select"
            field["options"] = [{"value": "0", "label": "— 默认 —"}] + content_type_options
        elif c == "region_id":
            field["type"] = "select"
            field["options"] = [{"value": "0", "label": "— 未指定 —"}] + region_options
        # 开关型：补是/否选项（前端用开关渲染，选项用于列展示）
        elif typ == "switch":
            field["options"] = BOOL_OPTIONS
        form.append(field)
    # 需求：产品和案例需要封面图 + 图集（图集存 extra JSON）
    if resource == "content" and force_model in ("product", "case") and not any(f["key"] == "album" for f in form):
        insert_at = next((i for i, f in enumerate(form) if f["key"] == "body"), len(form))
        form.insert(insert_at, {"key": "album", "label": "图集", "type": "image_multi"})
    # 需求：内容表单第一行是标题；发布时间新增时默认当前时间
    if resource == "content":
        order = ["title", "slug", "category_id", "cover", "album", "publish_at", "body", "is_top", "is_hot", "status", "seo_title", "seo_keywords", "seo_description", "sort"]
        rank = {k: i for i, k in enumerate(order)}
        form.sort(key=lambda f: rank.get(f["key"], 50))
        for f in form:
            if f["key"] == "publish_at" and f.get("type") != "hidden":
                f["value"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if f["key"] == "title":
                f["full"] = True  # 需求：内容表单第一行是标题（独占整行）
            # 封面图上传区：推荐比例 16:9（上传组件据此生成提示文案）
            if f["key"] == "cover":
                f["ratio"] = "16:9"
        # 内容模型扩展字段：追加到表单（数据存 extra JSON）
        if force_model and model_extra_fields:
            form.append({"key": "_section_extra", "label": "扩展字段", "type": "section"})
            for ef in model_extra_fields:
                form.append({
                    "key": "extra." + ef["name"], "label": ef.get("label") or ef["name"],
                    "type": ef.get("type", "text"), "required": bool(ef.get("required")),
                    "value": ef.get("default", ""), "_extra": True,
                })
    # 需求（2026-11-24）：分类「访问别名」必填；文章/项目/案例 分类+正文必填，页面正文必填，banner 封面必传
    if resource == "category":
        for f in form:
            if f["key"] == "slug":
                f["required"] = True
    _force_model_required(form, force_model)
    return {"title": title or resource, "model": resource, "columns": columns,
            "filters": filters, "form": form, "readonly": readonly, "size": 10}


def _dynamic_options(db):
    """从当前站点库读取站点 / 栏目 / 内容类型 / 地区选项，供下拉使用。"""
    try:
        sites = [{"value": str(s.id), "label": s.name} for s in db.scalars(select(Site)).all()][:30]
    except Exception:
        sites = []
    try:
        cats = [{"value": str(c.id), "label": c.name, "model": c.model, "pid": c.pid, "sort": c.sort}
                for c in db.scalars(select(Category).where(Category.deleted_at.is_(None))).all()][:200]
    except Exception:
        cats = []
    try:
        ctypes = [{"value": str(t.id), "label": t.name} for t in db.scalars(select(MODEL_REGISTRY["content_type"])).all()][:100]
    except Exception:
        ctypes = []
    try:
        regions = [{"value": str(r.id), "label": r.name} for r in db.scalars(select(Region)).all()][:300]
    except Exception:
        regions = []
    # 启用的内容模型（按 code）：供分类管理「内容模型」下拉动态使用
    try:
        enabled_models = [{"value": t.code, "label": t.name}
                          for t in db.scalars(select(ContentType).where(ContentType.status == 1)
                                              .order_by(ContentType.id)).all()]
    except Exception:
        enabled_models = []
    return sites, cats, ctypes, regions, enabled_models


@router.get("/crud/config")
async def crud_config(key: str, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """按菜单 key 返回 CRUD 配置。"""
    sites, cats, ctypes, regions, enabled_models = _dynamic_options(db)
    dyn = dict(site_options=sites, category_options=cats, content_type_options=ctypes,
               region_options=regions, enabled_model_options=enabled_models)
    # content-{code} 通用映射：任意启用的内容模型都走通用 CRUD 页（文章/产品/案例/banner/单页/自定义模型…）
    # 动态模型 key 不在 RESOURCE_MAP，按 code 查 content_type 解析（查不到则不返回配置）
    resource_map = dict(RESOURCE_MAP)
    if key not in resource_map and key.startswith("content-") and key not in {"content-category", "content-recycle"}:
        ct = db.scalars(select(ContentType).where(ContentType.code == key[len("content-"):])).first()
        if ct is not None:
            resource_map[key] = ("content", f"内容管理 / {ct.name}")
    if key in resource_map:
        resource, title = resource_map[key]
        force_model = None
        if key.startswith("content-") and key not in {"content-category", "content-recycle"}:
            force_model = key[len("content-"):]
        readonly = key in {"form-record", "setting-log", "tool-task-log", "order-list", "member-balance-log", "member-point-log"}
        # 内容模型扩展字段（dev-content-model 定义）：追加到内容表单
        model_extra_fields = None
        if force_model:
            try:
                ct = db.scalars(select(ContentType).where(ContentType.code == force_model)).first()
                if ct:
                    model_extra_fields = json.loads(ct.fields or "[]")
            except (ValueError, TypeError):
                model_extra_fields = None
        cfg = build_config(resource, title, force_model, readonly, model_extra_fields=model_extra_fields, **dyn)
        if force_model:
            cfg["fixed_filter"] = {"model": force_model}
        if key == "content-recycle":
            cfg["recycle"] = True
        # 需求：CRUD 页支持扩展行内动作（图标按钮，如 复制密钥 / 重新生成 / 立即执行）
        if key == "dev-openapi":
            cfg["row_actions"] = [
                {"key": "copy_key", "icon": "bi-clipboard", "title": "复制 AppKey"},
                {"key": "copy_secret", "icon": "bi-key", "title": "复制 AppSecret"},
                {"key": "regen", "icon": "bi-arrow-repeat", "title": "重新生成密钥",
                 "confirm": "旧 AppSecret 将立即失效，使用旧密钥的调用方会全部鉴权失败。确定继续吗？"},
            ]
        if key == "tool-task":
            cfg["row_actions"] = [
                {"key": "run", "icon": "bi-play-fill", "title": "立即执行"},
                {"key": "log", "icon": "bi-file-text", "title": "查看日志"},
            ]
        # 表单提交记录：查看详情（按表单字段配置可视化展示提交内容）
        if key == "form-record":
            cfg["row_actions"] = [
                {"key": "view", "icon": "bi-eye", "title": "查看详情"},
            ]
        # 操作日志：查看详情
        if key == "setting-log":
            cfg["row_actions"] = [
                {"key": "view", "icon": "bi-eye", "title": "查看详情"},
            ]
        return ok(cfg)
    return ok(build_config(key, key, **dyn))


# 图标选择器可选图标（Bootstrap Icons 常用集）
@router.get("/icon-options")
async def icon_options(username: str = Depends(current_admin)):
    icons = [
        "bi-house-door", "bi-diagram-3", "bi-geo-alt", "bi-ui-checks-grid", "bi-arrow-left-right", "bi-sliders",
        "bi-folder", "bi-folder2-open", "bi-tags", "bi-file-earmark-text", "bi-box", "bi-briefcase", "bi-trash3",
        "bi-images", "bi-people", "bi-person-badge", "bi-mortarboard", "bi-cash-coin", "bi-stars", "bi-cart-check",
        "bi-arrow-return-left", "bi-credit-card", "bi-input-cursor-text", "bi-envelope-paper", "bi-chat-dots",
        "bi-alarm", "bi-list-ul", "bi-download", "bi-shield", "bi-shield-lock", "bi-person-gear", "bi-gear",
        "bi-translate", "bi-card-text", "bi-cloud-upload", "bi-chat-square-text", "bi-robot", "bi-lock",
        "bi-clock-history", "bi-table", "bi-palette", "bi-puzzle", "bi-braces", "bi-newspaper", "bi-building",
        "bi-graph-up", "bi-lightning", "bi-star", "bi-heart", "bi-flag", "bi-book", "bi-camera", "bi-phone",
        "bi-globe", "bi-link-45deg", "bi-clipboard-check", "bi-calendar-event", "bi-bell", "bi-question-circle",
    ]
    return ok([{"value": i, "label": i.replace("bi-", "")} for i in icons])


@router.get("/list/{resource}")
async def crud_list(request: Request, resource: str, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    if resource not in MODELS:
        return fail("资源不存在", 20002)
    params = dict(request.query_params)
    recycle = params.pop("recycle", "") == "1"
    if resource in SOFT:
        model = MODELS[resource]
        # 回收站：只查已删除；正常：只查未删除
        params_extra = {}
        stmt = select(model)
        if recycle:
            stmt = stmt.where(model.deleted_at.is_not(None))
        else:
            stmt = stmt.where(model.deleted_at.is_(None))
        from app.content.service import paginate_stmt
        data = paginate_stmt(db, model, stmt, params)
    else:
        data = paginate(db, MODELS[resource], params)
    if resource == "content":
        cats = {c.id: c.name for c in db.scalars(select(Category)).all()}
        for row in data["list"]:
            row["category_name"] = cats.get(row.get("category_id"), "")
            # 扩展字段展开为 x_* 列（列表显示 list=1 的扩展字段由 build_config 注入列）
            ex = row.get("extra")
            if isinstance(ex, str):
                try:
                    ex = json.loads(ex or "{}")
                except ValueError:
                    ex = {}
            if isinstance(ex, dict):
                for k, v in ex.items():
                    row["x_" + str(k)] = v
    if resource in {"content", "category"}:
        # 需求：列表「内容模型」列显示模型名称（如 新闻/单页），不显示模型标识（article/page）
        names = {ct.code: ct.name for ct in db.scalars(select(ContentType)).all()}
        for row in data["list"]:
            code = str(row.get("model") or "")
            row["model_name"] = names.get(code, code)
    if resource == "media":
        # 上传人：admin_user_id -> nickname/username；历史数据为 0 显示「系统」
        users = {u.id: (u.nickname or u.username) for u in db.scalars(select(AdminUser)).all()}
        for row in data["list"]:
            row["uploader"] = users.get(row.get("admin_user_id"), "系统" if not row.get("admin_user_id") else "—")
    if resource == "form_record":
        forms = {f.id: f for f in db.scalars(select(FormModel)).all()}
        for row in data["list"]:
            # 历史数据只写了 form_id，兜底取 form_id
            fm = forms.get(row.get("form_model_id")) or forms.get(row.get("form_id"))
            row["form_type"] = fm.name if fm else "—"
            # 可视化：按表单字段配置把 data JSON 解析为 [{label, value}]，
            # 选项值翻译为选项名称（如 1 -> 是），供前端直接渲染而非显示 JSON
            try:
                fdefs = json.loads(fm.fields or "[]") if fm else []
            except (ValueError, TypeError):
                fdefs = []
            try:
                dmap = json.loads(row.get("data") or "{}")
            except (ValueError, TypeError):
                dmap = {}
            if not isinstance(dmap, dict):
                dmap = {}
            if not isinstance(fdefs, list):
                fdefs = []
            fmap = {}
            for fd in fdefs:
                if isinstance(fd, dict):
                    fkey = fd.get("field") or fd.get("name") or fd.get("key")
                    if fkey:
                        fmap[fkey] = fd
            view = []
            for k, v in dmap.items():
                fd = fmap.get(k) or {}
                label = fd.get("label") or k
                opts = {str(o.get("value")): str(o.get("label") or o.get("value"))
                        for o in (fd.get("options") or []) if isinstance(o, dict)}
                if fd.get("type") == "switch":
                    val = "是" if str(v) in ("1", "true", "True") else "否"
                elif opts:
                    parts = [opts.get(str(p).strip(), str(p)) for p in str(v or "").split(",") if str(p).strip()]
                    val = "、".join(parts)
                else:
                    val = "" if v is None else str(v)
                view.append({"label": str(label), "value": val})
            row["data_view"] = view
    return ok(data)


@router.get("/detail/{resource}/{item_id}")
async def crud_detail(resource: str, item_id: int, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    if resource not in MODELS:
        return fail("资源不存在", 20002)
    item = get_item(db, MODELS[resource], item_id)
    # 内容：把 extra 中的图集还原为 album 字段供表单回显
    if resource == "content" and item:
        try:
            extra = json.loads(item.get("extra") or "{}")
        except ValueError:
            extra = {}
        if isinstance(extra, dict) and extra.get("album"):
            item["album"] = json.dumps(extra["album"], ensure_ascii=False)
    return ok(item)


def _auto_slug(source: str) -> str:
    """访问别名自动生成：中文转拼音，英文/数字保留原文。"""
    import re as _re
    src = str(source or "").strip()
    if not src:
        return ""
    # 已是纯英文/数字/连字符 → 直接使用
    if _re.fullmatch(r"[A-Za-z0-9_-]+", src):
        return src.lower()
    slug = ""
    try:
        from pypinyin import lazy_pinyin, Style
        parts = lazy_pinyin(src, style=Style.NORMAL, errors=lambda c: [c] if _re.match(r"[A-Za-z0-9]", c) else [""])
        slug = "".join(p for p in parts if p)
    except Exception:
        slug = _re.sub(r"[^A-Za-z0-9]+", "", src)
    slug = _re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:100]
    return slug


@router.post("/save/{resource}")
async def crud_save(request: Request, resource: str, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    if resource not in MODELS:
        return fail("资源不存在", 20002)
    model = MODELS[resource]
    payload = dict(payload)
    item_id = payload.pop("id", None)
    # 图集（产品/案例）：非模型列，先取出再过滤
    album_raw = payload.pop("album", None)
    # 内容模型扩展字段（extra. 前缀）：收集后存入 extra JSON
    extra_data = {k[len("extra."):]: v for k, v in list(payload.items()) if k.startswith("extra.")}
    for k in list(extra_data):
        payload.pop("extra." + k, None)
    # 清理前端注入的非模型字段
    allowed = {c.name for c in model.__table__.columns}
    payload = {k: v for k, v in payload.items() if k in allowed and k not in ("created_at", "updated_at", "deleted_at", "deleted_by")}

    # 内容表单：后端自动生成 作者 / 发布时间 / 摘要（前端不体现这些字段）
    if resource == "content":
        import re as _re
        # 需求（2026-11-24）：新增内容时作者自动带入当前登录管理员的昵称；编辑不覆盖原作者
        if not item_id:
            _up = db.scalar(select(AdminUser).where(AdminUser.username == username))
            payload["author"] = (_up.nickname if _up and _up.nickname else username)
        # 访问别名：用户未自定义时，默认按标题拼音或原始英文生成
        if not str(payload.get("slug") or "").strip():
            payload["slug"] = _auto_slug(payload.get("title") or "")
        # 图集（产品/案例）+ 模型扩展字段：统一存入 extra JSON
        extra_store = {}
        album = album_raw
        if album is not None:
            if isinstance(album, str):
                try:
                    album = json.loads(album)
                except ValueError:
                    album = [u for u in album.split(",") if u.strip()]
            if not isinstance(album, list):
                album = []
            extra_store["album"] = album
        if extra_data:
            # 编辑时保留已有的其他 extra 键（如 album）
            try:
                existed = json.loads(payload.get("extra") or "{}")
                if isinstance(existed, dict):
                    extra_store = {**existed, **extra_data}
            except ValueError:
                pass
        if extra_store:
            payload["extra"] = json.dumps(extra_store, ensure_ascii=False)
        if not item_id or not payload.get("publish_at"):
            payload["publish_at"] = datetime.now()
        else:
            # 前端可能传字符串日期，转成 datetime 供 SQLAlchemy DateTime 使用
            pv = payload.get("publish_at")
            if isinstance(pv, str) and pv:
                parsed = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        parsed = datetime.strptime(pv.strip(), fmt); break
                    except ValueError:
                        continue
                payload["publish_at"] = parsed or datetime.now()
        # 摘要从正文自动生成（去标签、截断 120 字）
        html = payload.get("body") or payload.get("main_content") or ""
        if isinstance(html, str) and html:
            text = _re.sub(r"<[^>]+>", "", html)
            text = _re.sub(r"\s+", " ", text).strip()
            payload["summary"] = text[:120]
        # 需求（2026-11-24）：内容模型字段开启「值唯一」后，新增/编辑做唯一性校验
        _model_code = str(payload.get("model") or "")
        if _model_code:
            _ct = db.scalar(select(ContentType).where(ContentType.code == _model_code))
            if _ct:
                try:
                    _fdefs = json.loads(_ct.fields or "[]")
                except (ValueError, TypeError):
                    _fdefs = []
                _uniq = [fd for fd in _fdefs if isinstance(fd, dict) and fd.get("unique")]
                if _uniq:
                    _others = db.scalars(select(Content).where(
                        Content.model == _model_code, Content.deleted_at.is_(None))).all()
                    _new_extra = {}
                    try:
                        _new_extra = json.loads(payload.get("extra") or "{}")
                    except (ValueError, TypeError):
                        _new_extra = {}
                    if not isinstance(_new_extra, dict):
                        _new_extra = {}
                    for _fd in _uniq:
                        _n = _fd.get("name")
                        if _fd.get("sys"):
                            _newv = payload.get(_n)
                            if _newv in (None, ""):
                                continue
                            _dup = [r.id for r in _others
                                    if r.id != (item_id or 0) and str(getattr(r, _n, "") or "") == str(_newv)]
                        else:
                            _newv = _new_extra.get(_n)
                            if _newv in (None, ""):
                                continue
                            _dup = []
                            for r in _others:
                                if r.id == (item_id or 0):
                                    continue
                                try:
                                    _rex = json.loads(r.extra or "{}")
                                except (ValueError, TypeError):
                                    _rex = {}
                                if isinstance(_rex, dict) and str(_rex.get(_n) or "") == str(_newv):
                                    _dup.append(r.id)
                        if _dup:
                            return fail(f"「{_fd.get('label') or _n}」的值「{_newv}」已存在（唯一性校验不通过）")

    if resource == "admin_user":
        pwd = payload.pop("password_hash", "")
        if pwd and not password_valid(db, pwd):
            return fail(get_password_rule(db)["tip"])
        if item_id:
            if pwd:
                row = db.get(AdminUser, int(item_id))
                if row:
                    row.password_hash = hash_password(pwd)
        else:
            payload["password_hash"] = hash_password(pwd or "Admin@2026")
            payload.setdefault("is_super", 1 if payload.get("role") == "super" else 0)
    # 分类：访问别名未填时按名称自动生成；需求（2026-11-24）必填且正则校验：
    # 英文字母开头，可拼接 _ 和 -，不允许其他字符
    if resource == "category":
        if not str(payload.get("slug") or "").strip():
            payload["slug"] = _auto_slug(payload.get("name") or "")
        import re as _re_cat
        from app.pages.resolve import RESERVED_SLUGS
        _slug = str(payload.get("slug") or "").strip()
        if not _re_cat.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", _slug):
            return fail("访问别名必须以英文字母开头，仅可包含英文字母、数字、下划线(_)和连字符(-)")
        if _slug.lower() in RESERVED_SLUGS:
            return fail("该访问别名是系统保留词（search/admin/api/uploads/theme-assets/theme-libs），请更换")
    # 素材库「添加」弹窗：上传接口已自动入库，保存时按路径找到已有记录更新文件名等信息，避免重复插入
    if resource == "media" and not item_id:
        p = str(payload.get("path") or "").strip()
        if p:
            existing = db.scalar(select(Media).where(Media.path == p))
            if existing:
                item_id = existing.id
    if item_id:
        row = update_item(db, model, int(item_id), payload)
        action = "edit"
    else:
        row = create_item(db, model, payload)
        action = "add"
    _, _, cache = ctx(request)
    cache.clear()
    log_op(db, username, resource, action, str(item_id or row.get("id")), str(payload)[:500],
           client_ip(request))
    return ok(row, "保存成功")


@router.post("/delete/{resource}")
async def crud_delete(request: Request, resource: str, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    if resource not in MODELS:
        return fail("资源不存在", 20002)
    ids = [int(i) for i in (payload.get("ids") or ([payload["id"]] if payload.get("id") else []))]
    hard = bool(payload.get("hard"))
    model = MODELS[resource]
    n = 0
    if hasattr(model, "deleted_at") and not hard:
        # 软删除
        for i in ids:
            row = db.get(model, i)
            if row:
                row.deleted_at = datetime.now()
                row.deleted_by = 1
                n += 1
        db.commit()
    else:
        n = delete_items(db, model, ids)
    _, _, cache = ctx(request)
    cache.clear()
    log_op(db, username, resource, "delete", str(ids), f"删除 {n} 条", client_ip(request))
    return ok({"deleted": n}, "删除成功")


@router.post("/restore/{resource}")
async def crud_restore(request: Request, resource: str, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    model = MODELS.get(resource)
    if model is None or not hasattr(model, "deleted_at"):
        return fail("资源不支持恢复", 20002)
    ids = [int(i) for i in (payload.get("ids") or [])]
    n = 0
    for i in ids:
        row = db.get(model, i)
        if row:
            row.deleted_at = None
            row.deleted_by = None
            n += 1
    db.commit()
    request.app.state.cache.clear()
    log_op(db, username, resource, "restore", str(ids), f"恢复 {n} 条", "")
    return ok({"restored": n}, "恢复成功")


# ---------------- 设置 ----------------
@router.get("/settings")
async def get_settings(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    rows = db.scalars(select(Setting)).all()
    return ok({r.key: jloads(r.value, r.value) for r in rows})


@router.post("/settings")
async def save_settings(request: Request, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    for key, value in payload.items():
        row = db.scalar(select(Setting).where(Setting.key == key))
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if row is None:
            db.add(Setting(key=key, value=raw, group="basic"))
        else:
            row.value = raw
    db.commit()
    request.app.state.cache.clear()
    # 后台访问防护配置（IP 名单/后台地址）已变更：立即刷新防护中间件缓存
    if {"admin_path", "admin_ip_mode", "admin_ip_rules"} & set(payload):
        setattr(request.app.state, "_admin_guard", None)
    log_op(db, username, "setting", "edit", "basic", str(payload)[:500], "")
    return ok(msg="设置已保存")


@router.post("/reseed")
async def reseed(request: Request, username: str = Depends(current_admin)):
    cfg, db, cache = ctx(request)
    session = db.session()
    try:
        result = seed_site(session, cfg, cfg.root / "storage" / "seed.json", force=True)
    finally:
        session.close()
    cache.clear()
    # 重新扫描素材入库
    try:
        from .maintenance import import_uploads_to_media
        import_uploads_to_media(cfg)
    except Exception:
        pass
    return ok(result, "示例数据已重新初始化")


# ---------------- 上传 ----------------
_RASTER_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"}


def _upload_limits() -> tuple[int, int]:
    """(单文件大小上限 MB, 图片像素总量上限)；可用 MAX_UPLOAD_MB / MAX_UPLOAD_PIXELS 调整。"""
    import os
    try:
        mb = int(os.getenv("MAX_UPLOAD_MB", "20"))
    except ValueError:
        mb = 20
    try:
        px = int(os.getenv("MAX_UPLOAD_PIXELS", "40000000"))
    except ValueError:
        px = 40000000
    return max(1, mb), max(1_000_000, px)


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), username: str = Depends(current_admin)):
    cfg, db, _ = ctx(request)
    raw = await file.read()
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    allowed = {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "pdf", "doc", "docx", "zip", "xls", "xlsx", "txt"}
    if ext not in allowed:
        return fail(f"不允许的文件类型: .{ext}")
    # 大小硬限制：从源头拦截超大文件，避免内存/解码开销
    max_mb, max_pixels = _upload_limits()
    if len(raw) > max_mb * 1024 * 1024:
        return fail(f"文件过大：单个文件不得超过 {max_mb}MB")
    # 图片分辨率硬限制：超大分辨率图片解码会打爆内存（Pillow 解码内存约为像素数×3~4 字节）
    if ext in _RASTER_EXTS:
        from io import BytesIO
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(BytesIO(raw)) as im:
                w, h = im.size
            if w * h > max_pixels or max(w, h) > 12000:
                return fail(f"图片分辨率过大（{w}x{h}）：最长边不得超过 12000px，总像素不得超过 {max_pixels // 10000}00 万，请压缩后再上传")
        except Exception:
            return fail("图片文件损坏或不是有效的图片文件")
    md5 = hashlib.md5(raw).hexdigest()
    file_type = "image" if ext in {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico"} else "file"
    # 存储目录模板：默认 {filetype}/{year}{month}/{day}；文件名始终为 md5 全值 + 后缀
    try:
        from app.content.service import render_save_dir
        session_tpl = db.session()
        try:
            from sqlalchemy import select as _select
            from app.core.database import Setting as _Setting
            tpl_row = session_tpl.scalar(_select(_Setting).where(_Setting.key == "save_dir_template"))
            tpl = tpl_row.value if tpl_row and tpl_row.value else "{filetype}/{year}{month}/{day}"
        finally:
            session_tpl.close()
        sub_dir = render_save_dir(tpl, file_type)
    except Exception:
        _n = datetime.now()
        sub_dir = f"{file_type}/{_n:%Y%m}/%s" % f"{_n:%d}"
    name = f"{md5}.{ext}"
    target_dir = cfg.uploads_path / sub_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    if not path.exists():
        path.write_bytes(raw)
    url = "/uploads/" + sub_dir + "/" + name
    session = db.session()
    try:
        if not session.scalar(select(Media).where(Media.md5 == md5)):
            up = session.scalar(select(AdminUser).where(AdminUser.username == username))
            session.add(Media(filename=file.filename or name, path=url, storage_path=str(path),
                              file_type=file_type, file_ext=ext, ext=ext, size=len(raw),
                              mime=file.content_type or "", mime_type=file.content_type or "", md5=md5,
                              admin_user_id=up.id if up else 0))
            session.commit()
    finally:
        session.close()
    return ok({"url": url, "filename": file.filename, "size": len(raw)}, "上传成功")


@router.get("/files")
async def list_files(request: Request, username: str = Depends(current_admin)):
    cfg, _, _ = ctx(request)
    files = []
    for p in sorted(cfg.uploads_path.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            files.append({"name": p.name, "url": f"/uploads/{p.name}", "size": p.stat().st_size})
    return ok(files)


# ---------------- 维护操作（备份 / Sitemap / 同步 / 批量生成） ----------------
@router.post("/backup/create")
async def backup_create(request: Request, username: str = Depends(current_admin)):
    cfg, db, _ = ctx(request)
    from app.core.database import AdminBackup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{cfg.key}_{ts}.db"
    backup_dir = cfg.root / "backups"
    backup_dir.mkdir(exist_ok=True)
    target = backup_dir / name
    shutil.copy2(cfg.db_file, target)
    session = db.session()
    try:
        session.add(AdminBackup(site_id=0, filename=name, storage_path=str(target),
                                size=target.stat().st_size, status="success"))
        session.commit()
        log_op(session, username, "backup", "add", name, "创建备份", "")
    finally:
        session.close()
    return ok({"filename": name, "size": target.stat().st_size}, "备份成功")


@router.post("/station/sync")
async def station_sync(request: Request, payload: dict, username: str = Depends(current_admin)):
    """站群同步（本演示：写同步记录 + 返回预览结果）。"""
    cfg, db, _ = ctx(request)
    from app.core.database import SiteSyncLog
    session = db.session()
    try:
        batch = "SYNC" + datetime.now().strftime("%Y%m%d%H%M%S")
        n = session.scalar(select(func.count()).select_from(Site)) or 0
        row = SiteSyncLog(batch_no=batch, source_site_id=0, target_site_count=max(0, n - 1),
                          mode=payload.get("mode", "content"), strategy=payload.get("strategy", "skip"),
                          status="success", result=json.dumps({"message": "同步任务已完成", "sites": n}, ensure_ascii=False))
        session.add(row)
        session.commit()
        log_op(session, username, "station_sync", "sync", batch, str(payload)[:300], "")
    finally:
        session.close()
    return ok({"batch_no": batch, "target_count": max(0, n - 1)}, "同步完成")


@router.post("/station/generate")
async def station_generate(request: Request, payload: dict, username: str = Depends(current_admin)):
    """批量生成子站点（按提供的名称列表生成 site + site_var 记录）。"""
    cfg, db, _ = ctx(request)
    names = payload.get("names") or []
    if isinstance(names, str):
        names = [x.strip() for x in names.replace("，", ",").split(",") if x.strip()]
    if not names:
        return fail("请提供要生成的地区/站点名称")
    session = db.session()
    created = 0
    try:
        for nm in names[:100]:
            code = "sub_" + hashlib.md5(nm.encode()).hexdigest()[:8]
            if not session.scalar(select(Site).where(Site.code == code)):
                session.add(Site(name=nm, code=code, domain=f"{code}.{cfg.key}.com",
                                 is_master=0, status=1, theme=cfg.theme,
                                 title_template=f"{{region}}-{cfg.short_name}",
                                 render_mode="dynamic", sort=created))
                created += 1
        session.commit()
        log_op(session, username, "station_generate", "add", str(len(names)), f"生成 {created} 个子站点", "")
    finally:
        session.close()
    return ok({"created": created, "total": len(names)}, f"已生成 {created} 个子站点")


# ---------------- 个人中心 ----------------
@router.get("/profile")
async def get_profile(username: str = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if not user:
        return fail("用户不存在")
    return ok({
        "username": user.username, "nickname": user.nickname or "", "avatar": user.avatar or "",
        "mobile": user.mobile or "", "email": user.email or "", "role": user.role,
        "status": user.status, "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else "",
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else "",
        "last_login_ip": user.last_login_ip or "",
    })


@router.post("/profile")
async def save_profile(request: Request, payload: dict, username: str = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if not user:
        return fail("用户不存在")
    for k in ("nickname", "mobile", "email", "avatar"):
        if k in payload and payload[k] is not None:
            setattr(user, k, str(payload[k]).strip()[:200])
    new_pwd = payload.get("new_password") or ""
    if new_pwd:
        if not password_valid(db, new_pwd):
            return fail(get_password_rule(db)["tip"])
        user.password_hash = hash_password(new_pwd)
    db.commit()
    log_op(db, username, "profile", "edit", username, "更新个人资料",
           client_ip(request))
    return ok(None, "保存成功")


@router.get("/profile/logs")
async def profile_logs(request: Request, username: str = Depends(current_admin), db: Session = Depends(get_db)):
    params = dict(request.query_params)
    page = max(1, int(params.get("page", 1)))
    size = min(50, max(1, int(params.get("size", 8))))
    stmt = select(OperationLog).where(OperationLog.admin_user == username)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(OperationLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ok({"total": total, "page": page, "size": size, "list": [to_dict(r) for r in rows]})


# ---------------- 权限树（角色可视化选择） ----------------
@router.get("/perm-tree")
async def perm_tree(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    rows = db.scalars(select(AdminPermission).order_by(AdminPermission.sort, AdminPermission.id)).all()
    items = [{"id": r.id, "pid": r.pid, "name": r.name, "key": r.key, "type": r.type,
              "icon": r.icon, "sort": r.sort, "status": r.status} for r in rows]
    by_pid: dict[int, list] = {}
    for it in items:
        by_pid.setdefault(int(it["pid"] or 0), []).append(it)

    def build(pid: int):
        out = []
        for it in sorted(by_pid.get(pid, []), key=lambda x: (x["sort"] or 0, x["id"])):
            it["children"] = build(it["id"])
            out.append(it)
        return out
    return ok(build(0))


# ---------------- 插件中心 ----------------
PLUGIN_CATALOG = [
    {
        "key": "oss", "name": "阿里云OSS云存储", "version": "1.0.0", "author": "企业管理系统",
        "desc": "将图片、附件等静态资源上传至阿里云对象存储 OSS，支持服务端中转与客户端直传两种模式，配合 CDN 实现全球加速。",
        "category": "云存储", "price": "免费", "icon": "bi-cloud-arrow-up-fill", "color": "#ff6a00",
        "downloads": 42856, "type": "upload",
        "fields": [
            {"key": "access_key_id", "label": "AccessKey ID", "type": "text"},
            {"key": "access_key_secret", "label": "AccessKey Secret", "type": "password"},
            {"key": "bucket", "label": "Bucket 名称", "type": "text"},
            {"key": "endpoint", "label": "Endpoint 节点", "type": "text", "placeholder": "如 oss-cn-hangzhou.aliyuncs.com"},
            {"key": "domain", "label": "自定义域名(可选)", "type": "text"},
        ],
    },
    {
        "key": "cos", "name": "腾讯云COS云存储", "version": "1.0.0", "author": "企业管理系统",
        "desc": "将图片、附件等静态资源上传至腾讯云对象存储 COS，支持静态网站托管与腾讯云 CDN 加速，适用于腾讯云生态。",
        "category": "云存储", "price": "免费", "icon": "bi-cloud-check-fill", "color": "#0052d9",
        "downloads": 31507, "type": "upload",
        "fields": [
            {"key": "secret_id", "label": "SecretId", "type": "text"},
            {"key": "secret_key", "label": "SecretKey", "type": "password"},
            {"key": "bucket", "label": "存储桶名称", "type": "text"},
            {"key": "region", "label": "地域", "type": "text", "placeholder": "如 ap-nanjing"},
            {"key": "domain", "label": "自定义域名(可选)", "type": "text"},
        ],
    },
    {
        "key": "ai", "name": "AI 智能创作", "version": "1.0.0", "author": "企业管理系统",
        "desc": "接入豆包 / DeepSeek / 智谱 AI 大模型。启用后内容列表出现「AI 添加」按钮，支持链接采集、提示词生成、根据站点内容生成文章，并可立即或定时发布。",
        "category": "AI 创作", "price": "免费", "icon": "bi-robot", "color": "#722ed1",
        "downloads": 18720, "type": "ai",
        "fields": [
            {"key": "provider", "label": "服务商", "type": "select", "options": ["豆包", "DeepSeek", "智谱AI"]},
            {"key": "model", "label": "模型", "type": "text"},
            {"key": "api_key", "label": "API Key", "type": "password"},
        ],
    },
]

PLUGIN_STATES = {"none": "未安装", "installed": "已安装", "enabled": "已启用"}


def _plugin_state(db: Session, key: str) -> str:
    row = db.scalar(select(Setting).where(Setting.key == f"plugin_{key}_state"))
    return row.value if row and row.value in PLUGIN_STATES else "none"


@router.get("/plugins")
async def plugin_list(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    out = []
    for p in PLUGIN_CATALOG:
        state = _plugin_state(db, p["key"])
        out.append({**p, "state": state, "state_text": PLUGIN_STATES[state], "enabled": state == "enabled"})
    return ok(out)


@router.post("/plugins/action")
async def plugin_action(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    key = payload.get("key", "")
    action = payload.get("action", "")
    plugin = next((p for p in PLUGIN_CATALOG if p["key"] == key), None)
    if not plugin:
        return fail("插件不存在")
    row = db.scalar(select(Setting).where(Setting.key == f"plugin_{key}_state"))
    cur = row.value if row else "none"
    if action == "install":
        if cur == "enabled":
            return fail("请先停用插件再卸载")
        new = "installed"
        msg = "插件安装成功"
    elif action == "uninstall":
        if cur == "enabled":
            return fail("请先停用插件再卸载")
        new = "none"
        msg = "插件已卸载"
    elif action == "enable":
        if cur == "none":
            return fail("请先安装插件")
        new = "enabled"
        msg = "插件已启用"
    elif action == "disable":
        if cur != "enabled":
            return fail("插件未启用")
        new = "installed"
        msg = "插件已停用"
    else:
        return fail("不支持的操作")
    if row is None:
        db.add(Setting(key=f"plugin_{key}_state", value=new, group="plugin"))
    else:
        row.value = new
    db.commit()
    log_op(db, username, "plugin", action, key, f"{plugin['name']} {msg}", "")
    return ok({"state": new, "state_text": PLUGIN_STATES[new]}, msg)


@router.get("/plugins/config")
async def plugin_config_get(key: str, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    plugin = next((p for p in PLUGIN_CATALOG if p["key"] == key), None)
    if not plugin:
        return fail("插件不存在")
    row = db.scalar(select(Setting).where(Setting.key == f"plugin_{key}_config"))
    try:
        cfg = json.loads(row.value) if row else {}
    except ValueError:
        cfg = {}
    return ok({"fields": plugin["fields"], "config": cfg})


@router.post("/plugins/config")
async def plugin_config_post(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    key = payload.get("key", "")
    plugin = next((p for p in PLUGIN_CATALOG if p["key"] == key), None)
    if not plugin:
        return fail("插件不存在")
    cfg = payload.get("config") or {}
    row = db.scalar(select(Setting).where(Setting.key == f"plugin_{key}_config"))
    val = json.dumps(cfg, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=f"plugin_{key}_config", value=val, group="plugin"))
    else:
        row.value = val
    db.commit()
    return ok(None, "配置已保存")


# ---------------- AI 插件（服务商 / 连通性测试 / 生成 / 发布） ----------------
AI_PROVIDERS = {
    "豆包": {
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "desc": "火山引擎（字节跳动），支持 doubao 系列与接入点 ID",
        "models": [
            "doubao-seed-1.6-250615", "doubao-seed-1.6-flash-250615", "doubao-seed-evolving",
            "doubao-1.5-pro-32k", "doubao-1.5-pro-256k", "doubao-1.5-lite-32k",
            "doubao-pro-32k", "doubao-pro-128k",
        ],
        "placeholder": "如 doubao-1.5-pro-32k 或接入点 ID ep-xxxx",
    },
    "DeepSeek": {
        "endpoint": "https://api.deepseek.com/chat/completions",
        "desc": "深度求索，V3 对话 / R1 推理",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "placeholder": "如 deepseek-chat",
    },
    "智谱AI": {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "desc": "智谱 BigModel，GLM 系列",
        "models": [
            "glm-4.5", "glm-4.5-air", "glm-4.5-flash", "glm-4-plus", "glm-4-air",
            "glm-4-airx", "glm-4-flashx", "glm-4-long", "glm-4v-plus",
        ],
        "placeholder": "如 glm-4.5-air",
    },
    "阿里云百炼": {
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "desc": "阿里云 DashScope，通义千问 Qwen 系列",
        "models": [
            "qwen3-max", "qwen3-235b-a22b", "qwen-max", "qwen-max-latest", "qwen-plus",
            "qwen-plus-latest", "qwen-turbo", "qwen-long", "qwen2.5-72b-instruct", "qwen2.5-32b-instruct",
        ],
        "placeholder": "如 qwen-plus",
    },
    "百度千帆": {
        "endpoint": "https://qianfan.baidubce.com/v2/chat/completions",
        "desc": "百度智能云千帆 V2，文心 ERNIE 系列",
        "models": [
            "ernie-4.5-turbo-128k", "ernie-4.5-turbo-32k", "ernie-4.5-8k", "ernie-4.5-turbo-vl-32k",
            "ernie-speed-128k", "ernie-lite-8k", "ernie-tiny-8k", "deepseek-v3",
        ],
        "placeholder": "如 ernie-4.5-turbo-128k",
    },
    "月之暗面 Kimi": {
        "endpoint": "https://api.moonshot.cn/v1/chat/completions",
        "desc": "Moonshot AI，Kimi 系列",
        "models": ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "placeholder": "如 moonshot-v1-32k",
    },
}

AI_SYSTEM_PROMPT = (
    "你是一名资深企业官网内容编辑。用户会给出素材或指令，请据此撰写一篇适合发布在企业官网上的原创中文文章。"
    "严格按以下格式输出：第一行只输出文章标题（一行，不要任何前缀），之后输出正文。"
    "正文使用简单的 HTML 段落标签（<p>…</p>），可分为 3-6 个段落，语言专业、通顺、可直接发布，不要输出任何解释说明。"
)


def _ai_conf(db: Session) -> tuple[bool, dict]:
    """返回 (插件是否启用, 配置 dict)。"""
    row = db.scalar(select(Setting).where(Setting.key == "plugin_ai_config"))
    try:
        cfg = json.loads(row.value) if row else {}
    except ValueError:
        cfg = {}
    return _plugin_state(db, "ai") == "enabled", cfg


async def _ai_chat(db: Session, messages: list, override: dict | None = None, timeout: int = 90) -> str:
    """调用服务商 OpenAI 兼容 chat/completions 接口，返回回复文本。"""
    import httpx
    _, cfg = _ai_conf(db)
    if override:
        cfg = {**cfg, **override}
    provider = str(cfg.get("provider") or "").strip()
    api_key = str(cfg.get("api_key") or "").strip()
    model = str(cfg.get("model") or "").strip()
    p = AI_PROVIDERS.get(provider)
    if not p:
        raise RuntimeError("请先在插件中心配置 AI 服务商")
    if not api_key:
        raise RuntimeError("请先填写 API Key")
    if not model:
        raise RuntimeError("请先选择模型")
    body = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 4000, "stream": False}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(p["endpoint"], json=body,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"接口返回 HTTP {resp.status_code}：{resp.text[:200]}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        raise RuntimeError(f"返回格式异常：{resp.text[:200]}")


async def _fetch_page_text(url: str) -> str:
    """抓取网页并提取纯文本（去 script/style/标签），截断至 8000 字。"""
    import httpx
    import re as _re
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; CMSBot/1.0)"}) as client:
        resp = await client.get(url)
    html = resp.text
    html = _re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<!--[\s\S]*?-->", " ", html, flags=_re.I)
    text = _re.sub(r"<[^>]+>", " ", html)
    return _re.sub(r"\s+", " ", text).strip()[:8000]


def _split_title_content(raw: str) -> tuple[str, str]:
    """第一行为标题，其余为正文。"""
    raw = (raw or "").strip()
    parts = raw.split("\n", 1)
    if len(parts) == 2:
        title = parts[0].strip().lstrip("#").strip()
        content = parts[1].strip()
    else:
        title, content = raw[:60], raw
    return title, content


@router.get("/ai/status")
async def ai_status(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    enabled, cfg = _ai_conf(db)
    return ok({"enabled": enabled, "provider": cfg.get("provider") or "", "model": cfg.get("model") or ""})


@router.get("/ai/providers")
async def ai_providers(username: str = Depends(current_admin)):
    return ok({k: {"models": v["models"], "placeholder": v["placeholder"],
                   "endpoint": v["endpoint"], "desc": v.get("desc", "")}
               for k, v in AI_PROVIDERS.items()})


@router.post("/ai/test")
async def ai_test(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """连通性测试：仅验证 服务商 + 模型 + Key 可用，不生成内容。"""
    override = {k: payload.get(k, "") for k in ("provider", "model", "api_key")}
    try:
        reply = await _ai_chat(db, [{"role": "user", "content": "ping，请只回复：pong"}],
                               override=override, timeout=30)
        return ok({"reply": reply[:50]}, "连通成功，模型可用")
    except Exception as e:  # noqa: BLE001
        return fail(f"连通失败：{e}")


@router.post("/ai/generate")
async def ai_generate(request: Request, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """三种模式生成文章：url 链接采集 / prompt 提示词生成 / site 根据当前网站生成。"""
    if not _ai_conf(db)[0]:
        return fail("AI 插件未启用，请先在插件中心开启")
    mode = payload.get("mode", "prompt")
    inp = str(payload.get("input") or "").strip()
    cfg, _, _ = ctx(request)
    try:
        if mode == "url":
            if not inp:
                return fail("请输入要采集的文章链接")
            text = await _fetch_page_text(inp)
            if len(text) < 50:
                return fail("该页面内容过少，无法采集（可能是动态渲染页面）")
            raw = await _ai_chat(db, [
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": f"请根据以下网页内容重新撰写一篇原创文章，不要照抄原文：\n\n来源：{inp}\n\n{text}"},
            ])
        elif mode == "site":
            settings = {r.key: r.value for r in db.scalars(select(Setting)).all()}
            cats = db.scalars(select(Category).where(Category.deleted_at.is_(None)).limit(20)).all()
            recent = db.scalars(
                select(Content).where(Content.deleted_at.is_(None), Content.status == "publish")
                .order_by(Content.created_at.desc()).limit(10)).all()
            site_info = (f"站点名称：{cfg.name}。行业/简介：{settings.get('site_description', '')}；"
                         f"主营关键词：{settings.get('site_keywords', '')}；联系方式：{settings.get('site_phone', '')}。"
                         f"已有分类：{('、'.join(c.name for c in cats)) or '无'}。"
                         f"最近已发布文章标题：{('；'.join(r.title for r in recent)) or '无'}。")
            extra = f"用户补充要求：{inp}" if inp else ""
            raw = await _ai_chat(db, [
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": f"请根据以下站点信息撰写一篇新的企业官网文章（如公司动态、行业知识、产品介绍等）：\n\n{site_info}\n{extra}"},
            ])
        else:
            if not inp:
                return fail("请输入生成提示词")
            raw = await _ai_chat(db, [
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": inp},
            ])
        title, content = _split_title_content(raw)
        if not title:
            return fail("AI 未返回有效标题，请重试")
        import re as _re
        return ok({"title": title[:200], "content": content, "summary": _re.sub(r"<[^>]+>", "", content).strip()[:120]})
    except RuntimeError as e:
        return fail(str(e))
    except Exception as e:  # noqa: BLE001
        return fail(f"生成失败：{type(e).__name__}: {e}")


@router.post("/ai/publish")
async def ai_publish(request: Request, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """将 AI 生成的内容入库：立即发布 / 定时发布（status=scheduled，由后台任务到期发布）。"""
    if not _ai_conf(db)[0]:
        return fail("AI 插件未启用，请先在插件中心开启")
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
        return fail("标题与正文不能为空")
    model_key = payload.get("model_key") if payload.get("model_key") in ("article", "product", "case") else "article"
    publish_type = payload.get("publish_type", "now")
    row = Content(
        title=title[:255], slug=_auto_slug(title), model=model_key,
        summary=str(payload.get("summary") or "")[:255],
        body=content, main_content=content,
        author=username, source="AI",
        status="publish" if publish_type == "now" else "scheduled",
        publish_at=datetime.now() if publish_type == "now" else None,
    )
    if publish_type == "scheduled":
        try:
            row.publish_at = datetime.strptime(str(payload.get("publish_at") or ""), "%Y-%m-%dT%H:%M")
        except ValueError:
            return fail("定时发布时间格式不正确")
    db.add(row)
    db.commit()
    log_op(db, username, "content", "ai_publish", row.id,
           f"AI 生成{'定时' if publish_type == 'scheduled' else ''}发布：{title}", model_key)
    return ok({"id": row.id, "status": row.status}, "定时发布已排期" if publish_type == "scheduled" else "发布成功")


# ---------------- 邮箱配置（SMTP） ----------------
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_ssl", "smtp_username", "smtp_sender_name", "smtp_password")


@router.post("/email/test")
async def email_test(request: Request, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """测试发送：直接使用表单当前填写的配置（无需先保存）。"""
    from app.core.mail import send_mail
    to = str(payload.get("to") or "").strip()
    if not to:
        return fail("请填写测试接收邮箱")
    cfg, _, _ = ctx(request)
    mail_cfg = {
        "host": payload.get("smtp_host"), "port": payload.get("smtp_port"),
        "ssl": payload.get("smtp_ssl"), "username": payload.get("smtp_username"),
        "password": payload.get("smtp_password"), "sender_name": payload.get("smtp_sender_name"),
    }
    okd, msg = send_mail(mail_cfg, to, f"【{cfg.name}】SMTP 配置测试邮件",
                         "这是一封测试邮件。\n\n如果您收到了它，说明当前邮箱配置填写正确，表单留言通知将可以正常发送。\n\n"
                         f"发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_op(db, username, "setting", "email_test", to, f"SMTP 测试发送至 {to}：{msg}", "")
    return ok({"detail": msg}, "测试邮件已发送，请查收") if okd else fail(f"发送失败：{msg}")


# ---------------- 主题管理 ----------------
THEME_CATALOG = [
    {"key": "default", "name": "简约默认", "desc": "经典蓝白企业风，适合大多数行业官网", "color": "#1677ff", "version": "1.0.0", "author": "官方"},
    {"key": "shugao", "name": "智造橙", "desc": "活力橙色工业智造风，大屏轮播+数字统计+方案手风琴", "color": "#f39800", "version": "1.0.0", "author": "官方"},
    {"key": "svolt", "name": "蜂巢深蓝", "desc": "深蓝新能源科技感，透明悬浮头部+大图板块+黄色点缀", "color": "#1E3083", "version": "1.0.0", "author": "官方"},
    {"key": "szjg", "name": "建工深红", "desc": "庄重深红建筑集团风，全屏大字banner+红色栏目tab+案例网格", "color": "#920d14", "version": "1.0.0", "author": "官方"},
    {"key": "zhongtai", "name": "工程蓝", "desc": "专业工程总包蓝，数字编号业务板块+资质荣誉墙+团队展示", "color": "#5590f7", "version": "1.0.0", "author": "官方"},
    {"key": "vanchor", "name": "化贸蓝", "desc": "外贸化工商务蓝，左文右图首屏+产品分类tab+行业应用矩阵", "color": "#2b5be2", "version": "1.0.0", "author": "官方"},
]


@router.get("/themes")
async def theme_list(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    row = db.scalar(select(Setting).where(Setting.key == "theme_active"))
    active = row.value if row and row.value else "default"
    out = [{**t, "active": t["key"] == active} for t in THEME_CATALOG]
    return ok(out)


@router.post("/themes/active")
async def theme_active(request: Request, payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    key = payload.get("key", "")
    if key not in {t["key"] for t in THEME_CATALOG}:
        return fail("主题不存在")
    row = db.scalar(select(Setting).where(Setting.key == "theme_active"))
    if row is None:
        db.add(Setting(key="theme_active", value=key, group="basic"))
    else:
        row.value = key
    db.commit()
    from app.core.state import set_static_version, set_theme
    ver = bump_static_version(db)
    set_theme(request.app, key)
    set_static_version(request.app, ver)
    request.app.state.cache.clear()
    log_op(db, username, "theme", "edit", key, "切换主题", "")
    return ok(None, "主题已切换")


# ---------------- 开放接口管理（消费方 AppKey/AppSecret） ----------------
def _gen_key(prefix: str, n: int = 16) -> str:
    return prefix + uuid.uuid4().hex[:n]


def _touch_today(c: ApiConsumer):
    """调用计数按日切换。"""
    today = datetime.now().strftime("%Y-%m-%d")
    if c.today_date != today:
        c.today_date = today
        c.today_calls = 0


@router.get("/openapi/list")
async def openapi_list(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    rows = db.scalars(select(ApiConsumer).order_by(ApiConsumer.id.desc())).all()
    return ok([{
        "id": r.id, "name": r.name, "app_key": r.app_key,
        "app_secret": r.app_secret, "total_calls": r.total_calls,
        "today_calls": r.today_calls, "status": r.status, "remark": r.remark,
        "created_at": r.created_at,
    } for r in rows])


@router.post("/openapi/save")
async def openapi_save(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """新增（自动生成 AppKey/AppSecret）或编辑；支持局部更新（如仅传 id+status 切换启停）。"""
    item_id = payload.get("id") or 0
    name = str(payload.get("name") or "").strip()
    if item_id:
        row = db.get(ApiConsumer, int(item_id))
        if not row:
            return fail("消费方不存在")
        # 局部更新：未传 name 时只更新传入的字段（修复：停用接口传 {id,status} 误报"请填写消费方名称"）
        if name:
            row.name = name
        if "remark" in payload:
            row.remark = str(payload.get("remark") or "")
        if "status" in payload:
            try:
                row.status = 1 if int(payload.get("status", 1)) else 0
            except (TypeError, ValueError):
                return fail("状态参数错误")
        log_op(db, username, "openapi", "edit", row.name, "编辑开放接口消费方", "")
    else:
        if not name:
            return fail("请填写消费方名称")
        row = ApiConsumer(name=name, app_key=_gen_key("ak_", 20), app_secret=_gen_key("sk_", 40),
                          status=int(payload.get("status", 1) or 1),
                          remark=str(payload.get("remark") or ""))
        db.add(row)
        log_op(db, username, "openapi", "add", name, "新增开放接口消费方", "")
    db.commit()
    return ok({"id": row.id}, "保存成功")


@router.post("/openapi/regen")
async def openapi_regen(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """重新生成 AppSecret：旧密钥立即失效。"""
    row = db.get(ApiConsumer, int(payload.get("id") or 0))
    if not row:
        return fail("消费方不存在")
    row.app_secret = _gen_key("sk_", 40)
    db.commit()
    log_op(db, username, "openapi", "edit", row.name, "重新生成 AppSecret", "")
    return ok({"app_secret": row.app_secret}, "已重新生成，旧密钥立即失效")


@router.post("/openapi/delete")
async def openapi_delete(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    row = db.get(ApiConsumer, int(payload.get("id") or 0))
    if not row:
        return fail("消费方不存在")
    name = row.name
    db.delete(row)
    db.commit()
    log_op(db, username, "openapi", "delete", name, "删除开放接口消费方", "")
    return ok(None, "删除成功")


# ---------------- 定时任务（对标宝塔计划任务） ----------------
from app.core import jobs as _cronjobs  # noqa: E402


@router.get("/cron/list")
async def cron_list(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    rows = db.scalars(select(AdminTask).order_by(AdminTask.id.desc())).all()
    out = []
    for r in rows:
        p = _cronjobs.task_params(r)
        out.append({
            "id": r.id, "name": r.name, "type": r.task_key,
            "type_name": _cronjobs.TASK_TYPES.get(r.task_key, r.task_key),
            "cycle": p.get("cycle", "day"), "cycle_cfg": p.get("cycle_cfg", {}),
            "cycle_desc": _cronjobs.describe_cycle(p.get("cycle", "day"), p.get("cycle_cfg", {})),
            "targets": p.get("targets", []), "keep": p.get("keep", 5),
            "compress": p.get("compress", 1), "exclude_dirs": p.get("exclude_dirs", ""),
            "db_lock": p.get("db_lock", 1), "url": p.get("url", ""), "script": p.get("script", ""),
            "status": r.status, "last_run_at": r.last_run_at.strftime("%Y-%m-%d %H:%M:%S") if r.last_run_at else "—",
            "next_run_at": r.next_run_at.strftime("%Y-%m-%d %H:%M:%S") if r.next_run_at else "—",
        })
    return ok(out)


@router.post("/cron/save")
async def cron_save(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    from core.cronjobs import _check, compute_next_run, task_params  # noqa: E402
    item_id = int(payload.get("id") or 0)
    name = str(payload.get("name") or "").strip()
    ttype = str(payload.get("type") or "").strip()
    cycle = str(payload.get("cycle") or "day")
    cycle_cfg = payload.get("cycle_cfg") or {}
    if not name:
        return fail("请填写任务名称")
    if ttype not in _cronjobs.TASK_TYPES:
        return fail("未知任务类型")
    err = _check(cycle, cycle_cfg)
    if err:
        return fail(f"执行周期校验失败：{err}")
    # 备份类任务才允许存储位置；时间参数前后端双重校验
    targets = payload.get("targets") if ttype in _cronjobs.BACKUP_TYPES else []
    params = {
        "cycle": cycle, "cycle_cfg": cycle_cfg,
        "targets": targets or [], "keep": int(payload.get("keep", 5) or 5),
        "compress": 1 if payload.get("compress", 1) else 0,
        "exclude_dirs": str(payload.get("exclude_dirs") or ""),
        "db_lock": 1 if payload.get("db_lock", 1) else 0,
        "url": str(payload.get("url") or ""), "script": str(payload.get("script") or ""),
    }
    if item_id:
        row = db.get(AdminTask, item_id)
        if not row:
            return fail("任务不存在")
        row.name, row.task_key, row.params = name, ttype, json.dumps(params, ensure_ascii=False)
        row.next_run_at = compute_next_run(cycle, cycle_cfg)
        log_op(db, username, "cron", "edit", name, "编辑定时任务", "")
    else:
        row = AdminTask(name=name, task_key=ttype, cron="",
                        params=json.dumps(params, ensure_ascii=False), status=1,
                        next_run_at=compute_next_run(cycle, cycle_cfg))
        db.add(row)
        log_op(db, username, "cron", "add", name, "新增定时任务", "")
    db.commit()
    return ok({"id": row.id}, "保存成功")


@router.post("/cron/toggle")
async def cron_toggle(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    row = db.get(AdminTask, int(payload.get("id") or 0))
    if not row:
        return fail("任务不存在")
    row.status = 0 if row.status == 1 else 1
    db.commit()
    return ok({"status": row.status}, "已" + ("启用" if row.status == 1 else "禁用"))


@router.post("/cron/delete")
async def cron_delete(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    row = db.get(AdminTask, int(payload.get("id") or 0))
    if not row:
        return fail("任务不存在")
    name = row.name
    # 同步删除任务日志
    for lg in db.scalars(select(AdminTaskLog).where(AdminTaskLog.task_id == row.id)).all():
        db.delete(lg)
    db.delete(row)
    db.commit()
    log_op(db, username, "cron", "delete", name, "删除定时任务", "")
    return ok(None, "删除成功")


@router.post("/cron/run")
async def cron_run(payload: dict, request: Request, username: str = Depends(current_admin)):
    """立即执行：不论周期是否到期。"""
    cfg, dbobj, _ = ctx(request)
    session = dbobj.session()
    try:
        row = session.get(AdminTask, int(payload.get("id") or 0))
        if not row:
            return fail("任务不存在")
        t0 = datetime.now()
        status, output = _cronjobs.run_task(row, cfg)
        cost_ms = int((datetime.now() - t0).total_seconds() * 1000)
        session.add(AdminTaskLog(task_id=row.id, status=status,
                                 result=f"[耗时 {cost_ms}ms]\n{output}", run_at=t0))
        row.last_run_at = t0
        p = _cronjobs.task_params(row)
        from core.cronjobs import compute_next_run
        row.next_run_at = compute_next_run(p.get("cycle", "day"), p.get("cycle_cfg", {}))
        session.commit()
    finally:
        session.close()
    return ok({"status": status, "output": output, "cost_ms": cost_ms},
              "执行成功" if status == "success" else "执行失败")


@router.get("/cron/logs")
async def cron_logs(task_id: int = 0, page: int = 1, size: int = 10,
                    db: Session = Depends(get_db), username: str = Depends(current_admin)):
    stmt = select(AdminTaskLog)
    if task_id:
        stmt = stmt.where(AdminTaskLog.task_id == task_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AdminTaskLog.id.desc())
                      .offset((page - 1) * size).limit(size)).all()
    return ok({"page": page, "size": size, "total": total, "list": [{
        "id": r.id, "task_id": r.task_id, "status": r.status,
        "result": r.result, "run_at": r.run_at.strftime("%Y-%m-%d %H:%M:%S") if r.run_at else "",
    } for r in rows]})


# ---------------- 内容模型：模型 CRUD + 字段管理（dev-content-model） ----------------
FIELD_TYPE_OPTIONS = ["text", "textarea", "editor", "password", "url", "email", "number",
                      "image_single", "image_multi", "file_single", "file_multi",
                      "select", "radio", "checkbox", "selectpage", "tag", "color", "switch",
                      "date", "date_range", "datetime", "datetime_range"]
# 旧类型 -> 新类型映射（历史字段定义兼容）
FIELD_TYPE_ALIAS = {"image": "image_single", "file": "file_single", "gallery": "image_multi"}

# 内置模型 code：不允许删除（允许改名/改图标/改字段）
BUILTIN_MODEL_CODES = {"article", "product", "case", "page", "banner"}

# 内容模型系统字段（label, 控件类型）：字段管理可见可编辑（label/必填/列表显示/隐藏/排序），标识与类型固定
SYS_CONTENT_FIELDS = [
    ("title", "标题", "text"), ("slug", "访问别名", "text"), ("category_id", "所属分类", "select"),
    ("cover", "封面图", "image_single"), ("publish_at", "发布时间", "datetime"), ("body", "正文内容", "editor"),
    ("is_top", "是否置顶", "switch"), ("is_hot", "是否热门", "switch"), ("status", "状态", "select"),
    ("seo_title", "seo标题", "text"), ("seo_keywords", "seo关键词", "tag"),
    ("seo_description", "seo描述", "textarea"), ("sort", "排序", "number"),
]
SYS_FIELD_MAP = {n: (l, t) for n, l, t in SYS_CONTENT_FIELDS}
SYS_FIELD_NAMES = set(SYS_FIELD_MAP)

# 系统字段 -> 内容表单控件映射（字段定义驱动表单时使用）
SYS_FORM_TYPES = {"title": "text", "slug": "text", "category_id": "select", "cover": "image_single",
                  "publish_at": "datetime", "body": "editor", "is_top": "switch", "is_hot": "switch",
                  "status": "select", "seo_title": "text", "seo_keywords": "tag",
                  "seo_description": "textarea", "sort": "number"}


@router.get("/content-model/list")
async def cm_list(db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """内容模型列表（含字段数）。"""
    rows = db.scalars(select(ContentType).order_by(ContentType.id)).all()
    data = []
    for r in rows:
        try:
            nfields = len(json.loads(r.fields or "[]"))
        except ValueError:
            nfields = 0
        data.append({
            "id": r.id, "name": r.name, "code": r.code, "icon": r.icon,
            "status": r.status, "fields_count": nfields,
            "builtin": 1 if r.code in BUILTIN_MODEL_CODES else 0,
        })
    return ok({"list": data})


@router.post("/content-model/save")
async def cm_save(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """新增/编辑内容模型。id 存在则编辑，否则新增。code 唯一。"""
    import re as _re
    item_id = int(payload.get("id") or 0)
    name = str(payload.get("name") or "").strip()
    code = str(payload.get("code") or "").strip().lower()
    icon = str(payload.get("icon") or "bi-file-earmark").strip() or "bi-file-earmark"
    # 注意：status=0 时 `0 or 1` 会得到 1，必须显式判 None（修复：禁用模型保存后仍显示启用）
    status = 1 if payload.get("status") is None else int(payload.get("status"))
    if not name:
        return fail("模型名称不能为空")
    if not code or not _re.fullmatch(r"[a-z][a-z0-9_]{0,31}", code):
        return fail("模型标识需以小写字母开头，仅含小写字母/数字/下划线，≤32 位")
    row = db.get(ContentType, item_id) if item_id else None
    # code 唯一校验
    dup = db.scalar(select(ContentType).where(ContentType.code == code))
    if dup and dup.id != item_id:
        return fail(f"模型标识「{code}」已存在")
    if row:
        old_code = row.code
        row.name, row.code, row.icon, row.status = name, code, icon, status
        action = "edit"
    else:
        row = ContentType(name=name, code=code, icon=icon, status=status, fields="[]")
        db.add(row)
        action = "add"
        old_code = ""
    db.commit()
    log_op(db, username, "content_model", action, name, f"内容模型{ '编辑' if action=='edit' else '新增'}（{old_code or code}）", "")
    return ok({"id": row.id}, "保存成功")


@router.post("/content-model/delete")
async def cm_delete(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """删除内容模型（内置模型不可删）。"""
    ids = payload.get("ids") or []
    if isinstance(ids, (int, str)):
        ids = [ids]
    ids = [int(i) for i in ids if str(i).isdigit()]
    if not ids:
        return fail("未选择模型")
    blocks, deleted = [], 0
    for item_id in ids:
        row = db.get(ContentType, item_id)
        if not row:
            continue
        if row.code in BUILTIN_MODEL_CODES:
            blocks.append(row.name)
            continue
        db.delete(row)
        deleted += 1
    if blocks:
        return fail(f"内置模型「{'、'.join(blocks)}」不可删除")
    db.commit()
    log_op(db, username, "content_model", "delete", ",".join(map(str, ids)), f"删除内容模型 {deleted} 个", "")
    return ok({"deleted": deleted}, "删除成功")



@router.get("/content-model/fields")
async def cm_fields(model_id: int, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    row = db.get(ContentType, int(model_id))
    if not row:
        return fail("内容模型不存在")
    try:
        fields = json.loads(row.fields or "[]")
    except ValueError:
        fields = []
    return ok({"model": {"id": row.id, "name": row.name, "code": row.code,
                         "icon": row.icon, "is_comment": row.is_comment, "is_order": row.is_order},
               "fields": fields})


@router.post("/content-model/save-fields")
async def cm_save_fields(payload: dict, db: Session = Depends(get_db), username: str = Depends(current_admin)):
    """字段定义：[{name,label,type,required,list,default,sys,hidden,options,sort}]；name 唯一、小写字母/数字/下划线。"""
    row = db.get(ContentType, int(payload.get("model_id") or 0))
    if not row:
        return fail("内容模型不存在")
    import re as _re
    fields = payload.get("fields") or []
    seen = set()
    clean = []
    for idx, f in enumerate(fields):
        name = str(f.get("name") or "").strip().lower()
        if not name or not _re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
            return fail(f"字段标识「{name or f.get('label')}」非法：需以小写字母开头，仅含小写字母/数字/下划线，≤32 位")
        if name in seen:
            return fail(f"字段标识「{name}」重复")
        if name in {"id", "content", "model", "extra"} or (name in SYS_FIELD_NAMES and not f.get("sys")):
            return fail(f"字段标识「{name}」与系统字段冲突")
        seen.add(name)
        is_sys = 1 if (f.get("sys") and name in SYS_FIELD_NAMES) else 0
        # 系统字段：标识/类型固定，不允许删除
        typ = SYS_FIELD_MAP[name][1] if is_sys else (f.get("type") if f.get("type") in FIELD_TYPE_OPTIONS else "text")
        # 选项配置（select/radio/checkbox）：[{label,value}]
        options = []
        if typ in ("select", "radio", "checkbox"):
            for o in (f.get("options") or []):
                ol, ov = str(o.get("label") or "").strip(), str(o.get("value") or "").strip()
                if ol and ov:
                    options.append({"label": ol, "value": ov})
        clean.append({
            "name": name, "label": str(f.get("label") or name),
            "type": typ, "required": 1 if f.get("required") else 0,
            "list": 1 if f.get("list") else 0,
            "unique": 1 if f.get("unique") else 0,
            "default": str(f.get("default") or ""),
            "sys": is_sys,
            "hidden": 1 if f.get("hidden") else 0,
            "options": options,
            # 弹窗关联选择：关联的内容模型 code（selectpage 专用）
            "rel_model": str(f.get("rel_model") or "") if typ == "selectpage" else "",
            "sort": idx + 1,
        })
    # 系统字段完整性校验：不允许删除系统字段（除「页面」外，访问别名(slug)可省略——保存时自动生成）
    required_sys = SYS_FIELD_NAMES if row.code == "page" else SYS_FIELD_NAMES - {"slug"}
    missing = [n for n in required_sys if n not in seen]
    if missing:
        return fail(f"系统字段不可删除：{ '、'.join(sorted(missing)) }")
    row.fields = json.dumps(clean, ensure_ascii=False)
    db.commit()
    log_op(db, username, "content_model", "edit", row.name,
           f"保存字段定义（{len(clean)} 个字段）", "")
    return ok({"fields": clean}, "字段定义已保存")
