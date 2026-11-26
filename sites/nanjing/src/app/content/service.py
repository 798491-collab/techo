"""共用数据服务：序列化、通用 CRUD、栏目树、种子数据初始化。

五个站点共用此文件；每站点的 storage/seed.json 提供各自的差异化数据。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Type

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import (
    AdminUser, AdminRole, AdminPermission, Category, Content, ContentType, FormModel, Media, Message, OperationLog,
    Setting, Tag,
)
from app.core.security import hash_password

# 菜单权威数据（分组/名称/图标/key）：router 菜单接口与权限节点对齐共用同一份，避免漂移
MENU_DEFS = [
    {"key": "dashboard", "name": "仪表盘", "icon": "bi-speedometer2", "group": "概览"},
    {"key": "station-site", "name": "站点列表", "icon": "bi-diagram-3", "group": "站群管理"},
    {"key": "station-region", "name": "地区库", "icon": "bi-geo-alt", "group": "站群管理"},
    {"key": "station-generate", "name": "批量生成", "icon": "bi-ui-checks-grid", "group": "站群管理"},
    {"key": "station-sync", "name": "站群同步", "icon": "bi-arrow-left-right", "group": "站群管理"},
    {"key": "station-setting", "name": "站群设置", "icon": "bi-sliders", "group": "站群管理"},
    {"key": "content-category", "name": "分类", "icon": "bi-folder", "group": "内容管理"},
    {"key": "content-article", "name": "新闻", "icon": "bi-file-earmark-text", "group": "内容管理"},
    {"key": "content-product", "name": "项目", "icon": "bi-box", "group": "内容管理"},
    {"key": "content-case", "name": "案例", "icon": "bi-briefcase", "group": "内容管理"},
    {"key": "content-banner", "name": "Banner", "icon": "bi-images", "group": "内容管理"},
    {"key": "content-page", "name": "页面", "icon": "bi-file-earmark", "group": "内容管理"},
    {"key": "content-recycle", "name": "回收站", "icon": "bi-trash3", "group": "内容管理"},
    {"key": "media", "name": "素材库", "icon": "bi-images", "group": "内容管理"},
    {"key": "member-list", "name": "会员列表", "icon": "bi-people", "group": "会员财务"},
    {"key": "member-group", "name": "会员分组", "icon": "bi-person-badge", "group": "会员财务"},
    {"key": "member-level", "name": "会员等级", "icon": "bi-mortarboard", "group": "会员财务"},
    {"key": "member-balance-log", "name": "余额流水", "icon": "bi-cash-coin", "group": "会员财务"},
    {"key": "member-point-log", "name": "积分流水", "icon": "bi-stars", "group": "会员财务"},
    {"key": "order-list", "name": "订单列表", "icon": "bi-cart-check", "group": "会员财务"},
    {"key": "order-refund", "name": "退款记录", "icon": "bi-arrow-return-left", "group": "会员财务"},
    {"key": "order-pay-setting", "name": "支付配置", "icon": "bi-credit-card", "group": "会员财务"},
    {"key": "form-model", "name": "表单模型", "icon": "bi-input-cursor-text", "group": "互动表单"},
    {"key": "form-record", "name": "提交记录", "icon": "bi-envelope-paper", "group": "互动表单"},
    {"key": "comment", "name": "评论列表", "icon": "bi-chat-dots", "group": "互动表单"},
    {"key": "tool-task", "name": "定时任务", "icon": "bi-alarm", "group": "运维工具"},
    {"key": "tool-task-log", "name": "任务日志", "icon": "bi-list-ul", "group": "运维工具"},
    {"key": "tool-seo", "name": "SEO配置", "icon": "bi-globe", "group": "运维工具"},
    {"key": "auth-admin-user", "name": "管理员列表", "icon": "bi-person-gear", "group": "权限与安全"},
    {"key": "auth-role", "name": "角色管理", "icon": "bi-shield", "group": "权限与安全"},
    {"key": "auth-permission", "name": "权限节点", "icon": "bi-shield-lock", "group": "权限与安全"},
    {"key": "setting-security", "name": "安全设置", "icon": "bi-lock", "group": "权限与安全"},
    {"key": "setting-log", "name": "操作日志", "icon": "bi-clock-history", "group": "权限与安全"},
    {"key": "setting-basic", "name": "基础设置", "icon": "bi-gear", "group": "系统配置"},
    {"key": "setting-switch", "name": "系统开关", "icon": "bi-toggle-on", "group": "系统配置"},
    {"key": "setting-lang", "name": "多语言管理", "icon": "bi-translate", "group": "系统配置"},
    {"key": "setting-lang-package", "name": "语言包管理", "icon": "bi-card-text", "group": "系统配置"},
    {"key": "setting-upload", "name": "上传设置", "icon": "bi-cloud-upload", "group": "系统配置"},
    {"key": "setting-sms", "name": "短信设置", "icon": "bi-chat-square-text", "group": "系统配置"},
    {"key": "setting-email", "name": "邮箱配置", "icon": "bi-envelope-at", "group": "系统配置"},
    {"key": "dev-content-model", "name": "内容模型", "icon": "bi-diagram-3", "group": "开发管理"},
    {"key": "dev-theme", "name": "主题管理", "icon": "bi-palette", "group": "开发管理"},
    {"key": "dev-plugin", "name": "插件管理", "icon": "bi-puzzle", "group": "开发管理"},
    {"key": "dev-openapi", "name": "开放API", "icon": "bi-braces", "group": "开发管理"},
    {"key": "dev-health", "name": "健康检查", "icon": "bi-heart-pulse", "group": "开发管理"},
]



def to_dict(obj: Any, exclude: tuple[str, ...] = ()) -> dict:
    if obj is None:
        return {}
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        value = getattr(obj, col.name)
        if isinstance(value, datetime):
            value = value.strftime("%Y-%m-%d %H:%M:%S")
        out[col.name] = value
    return out


def jloads(value: str | None, default: Any):
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# ---------------- 管理员密码规则（正则 + 提示文案，可在后台配置） ----------------
DEFAULT_PWD_REGEX = r"^(?=.{8,50}$)(?:(?=.*[0-9])(?=.*[A-Za-z])|(?=.*[0-9])(?=.*[^A-Za-z0-9\s])|(?=.*[A-Za-z])(?=.*[^A-Za-z0-9\s]))\S+$"
DEFAULT_PWD_TIP = "密码必须由数字、字母、特殊字符中的至少两类组成，长度 8-50 位，不能包含空格"


def get_password_rule(db: Session) -> dict:
    rows = {r.key: r.value for r in db.scalars(select(Setting)).all()}
    return {
        "regex": rows.get("admin_pwd_regex") or DEFAULT_PWD_REGEX,
        "tip": rows.get("admin_pwd_tip") or DEFAULT_PWD_TIP,
    }


def password_valid(db: Session, pwd: str) -> bool:
    import re as _re
    rule = get_password_rule(db)
    try:
        return bool(_re.match(rule["regex"], pwd or ""))
    except _re.error:
        return False


# ---------------- 静态资源版本号（清缓存时 +1） ----------------
STATIC_VERSION_KEY = "static_version"


def get_static_version(db: Session) -> str:
    row = db.scalar(select(Setting).where(Setting.key == STATIC_VERSION_KEY))
    return str(row.value) if row and row.value else "1"


def bump_static_version(db: Session) -> str:
    import re as _re
    cur = get_static_version(db)
    try:
        n = int(cur) + 1
    except (ValueError, TypeError):
        n = 2
    ver = str(n)
    row = db.scalar(select(Setting).where(Setting.key == STATIC_VERSION_KEY))
    if row:
        row.value = ver
    else:
        db.add(Setting(key=STATIC_VERSION_KEY, value=ver, group="basic"))
    db.commit()
    return ver


# ---------------- 通用 CRUD ----------------
TEXT_FIELDS = {"body", "summary", "description", "detail", "value", "fields", "data", "extra", "content", "seo_description"}


def paginate(db: Session, model: Type, params: dict, force: dict | None = None) -> dict:
    """通用分页查询：params 由请求提供，force 由服务端强制（如软删除过滤）。"""
    page = max(1, int(params.get("page", 1)))
    size = min(200, max(1, int(params.get("size", params.get("limit", 20)))))
    stmt = select(model)
    if force:
        for k, v in force.items():
            stmt = stmt.where(getattr(model, k) == v)
    keyword = (params.get("keyword") or params.get("search") or "").strip()
    if keyword:
        # 关键词多列模糊匹配：标题/名称/文件名/别名/编码/账号（媒体库等无 title/name 的模型也能搜索）
        kw_cols = [getattr(model, c) for c in ("title", "name", "filename", "slug", "code", "username") if hasattr(model, c)]
        if kw_cols:
            stmt = stmt.where(or_(*[c.like(f"%{keyword}%") for c in kw_cols]))
    for filt in ("model", "category_id", "status", "pid", "is_top", "is_hot", "is_read", "form_id", "file_type"):
        val = params.get(filt)
        if val not in (None, "", "all"):
            col = getattr(model, filt, None)
            if col is not None:
                stmt = stmt.where(col == val)
    sort_field = params.get("sort_field") or "sort"
    if hasattr(model, sort_field):
        col = getattr(model, sort_field)
        stmt = stmt.order_by(col.desc() if params.get("sort_order", "desc") == "desc" else col.asc())
    elif hasattr(model, "id"):
        stmt = stmt.order_by(getattr(model, "id").desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return {"total": total, "page": page, "size": size, "list": [to_dict(r) for r in rows]}


def paginate_stmt(db: Session, model: Type, stmt, params: dict) -> dict:
    """基于已有 select 语句的分页（用于软删除过滤等场景）。"""
    page = max(1, int(params.get("page", 1)))
    size = min(200, max(1, int(params.get("size", params.get("limit", 20)))))
    keyword = (params.get("keyword") or params.get("search") or "").strip()
    if keyword:
        kw_cols = [getattr(model, c) for c in ("title", "name", "filename", "slug", "code", "username") if hasattr(model, c)]
        if kw_cols:
            stmt = stmt.where(or_(*[c.like(f"%{keyword}%") for c in kw_cols]))
    for filt in ("model", "category_id", "status", "pid", "is_top", "is_hot", "is_read", "form_id", "form_model_id"):
        val = params.get(filt)
        if val not in (None, "", "all"):
            col = getattr(model, filt, None)
            if col is not None:
                stmt = stmt.where(col == val)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # 需求（2026-11-25）：后台内容列表与前台一致，按置顶 + 发布时间倒序（无发布时间回落创建时间）
    if hasattr(model, "publish_at"):
        stmt = stmt.order_by(model.is_top.desc(),
                             func.coalesce(model.publish_at, model.created_at).desc())
    else:
        stmt = stmt.order_by(getattr(model, "id").desc())
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return {"total": total, "page": page, "size": size, "list": [to_dict(r) for r in rows]}


def get_item(db: Session, model: Type, item_id: int) -> dict:
    return to_dict(db.get(model, item_id))


def create_item(db: Session, model: Type, data: dict) -> dict:
    allowed = {c.name for c in model.__table__.columns}
    row = model()
    for k, v in data.items():
        if k in allowed and k not in ("id", "created_at", "updated_at"):
            setattr(row, k, v)
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row)


def update_item(db: Session, model: Type, item_id: int, data: dict) -> dict | None:
    row = db.get(model, item_id)
    if row is None:
        return None
    allowed = {c.name for c in model.__table__.columns}
    for k, v in data.items():
        if k in allowed and k not in ("id", "created_at", "updated_at"):
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return to_dict(row)


def delete_items(db: Session, model: Type, ids: list[int]) -> int:
    count = 0
    for item_id in ids:
        row = db.get(model, item_id)
        if row is not None:
            db.delete(row)
            count += 1
    db.commit()
    return count


def log_op(db: Session, username: str, module: str, action: str, target: str = "", detail: str = "", ip: str = ""):
    db.add(OperationLog(admin_user=username, module=module, action=action,
                        target=str(target), detail=str(detail)[:1000], ip=ip))
    db.commit()


# ---------------- 栏目树 ----------------
def category_tree(categories: list[dict], pid: int = 0) -> list[dict]:
    nodes = []
    for c in sorted((x for x in categories if x.get("pid") == pid), key=lambda x: (x.get("sort", 0), x.get("id", 0))):
        node = dict(c)
        node["children"] = category_tree(categories, c["id"])
        nodes.append(node)
    return nodes


# ---------------- 种子数据 ----------------
RESERVED = {"created_at", "updated_at", "id"}


def _fill(model, data: dict):
    allowed = {c.name for c in model.__table__.columns}
    return {k: v for k, v in data.items() if k in allowed and k not in RESERVED}


def publish_due(db: Session) -> int:
    """将到期（publish_at <= 当前时间）的 scheduled 内容发布。返回发布条数。供后台定时任务与启动时调用。"""
    now = datetime.now()
    rows = db.scalars(select(Content).where(
        Content.status == "scheduled", Content.deleted_at.is_(None),
        Content.publish_at.isnot(None), Content.publish_at <= now,
    )).all()
    for r in rows:
        r.status = "publish"
    if rows:
        db.commit()
    return len(rows)


def render_save_dir(template: str, file_type: str) -> str:
    """解析存储目录模板，返回安全的相对目录（不含前导/尾随斜杠）。

    可用变量：{filetype} {year} {month} {day} {datetime} {timestamp} {rand6} {rand8}
    """
    import random
    import string
    import time
    now = datetime.now()
    rand6 = "".join(random.choice(string.digits) for _ in range(6))
    rand8 = "".join(random.choice(string.digits) for _ in range(8))
    mapping = {
        "filetype": file_type,
        "year": f"{now.year:04d}",
        "month": f"{now.month:02d}",
        "day": f"{now.day:02d}",
        "datetime": now.strftime("%Y%m%d%H%M%S"),
        "timestamp": str(int(time.time())),
        "rand6": rand6,
        "rand8": rand8,
    }
    out = str(template or "")
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", v)
    # 安全化：只允许字母数字、/、-、_、.，防止路径穿越
    out = "".join(ch for ch in out if ch.isalnum() or ch in "/-_.")
    parts = [p for p in out.split("/") if p and p not in (".", "..")]
    return "/".join(parts) or file_type


def _align_permission_tree(db: Session) -> int:
    """按 MENU_DEFS 对齐权限节点树（分组+菜单项）；button/特权节点保留并重挂。
    返回变更条数。结构未变时零改动，保持 id 稳定。"""
    # 扁平 MENU_DEFS 按 group 聚合 -> 分组顺序 + 组内菜单项
    groups: dict[str, list[dict]] = {}
    for m in MENU_DEFS:
        groups.setdefault(m["group"], []).append(m)
    # 期望 menu 节点：(name, key, pid_key, sort, icon)
    expected: list[tuple[str, str, str, int, str]] = []
    group_icons: dict[str, str] = {}
    for gi, (gname, items) in enumerate(groups.items(), 1):
        gkey = "group:" + gname
        gicon = items[0]["icon"] if items else "bi-menu-btn-wide"
        group_icons[gkey] = gicon
        expected.append((gname, gkey, "", gi, gicon))
        for mi, item in enumerate(items, 1):
            expected.append((item["name"], item["key"], gkey, mi, item["icon"]))
    group_keys = [k for k in group_icons]

    # 特权/按钮节点：统一纳入对齐（menu() 里的 EXTRA_PERMS 因 key 已存在不会重复补种）
    # (name, key, 归属分组名, sort, icon, type)
    priv = [
        ("邮箱配置", "setting.email", "系统配置", 6, "bi-envelope-at", "button"),
        ("AI插件管理", "ai.plugin", "开发管理", 4, "bi-robot", "button"),
        ("AI添加内容", "ai.add", "开发管理", 4, "bi-robot", "button"),
        ("新增内容", "content.add", "内容管理", 1, "bi-plus-lg", "button"),
        ("编辑内容", "content.edit", "内容管理", 2, "bi-pencil", "button"),
        ("删除内容", "content.delete", "内容管理", 3, "bi-trash", "button"),
    ]
    priv_keys = {pnode[1] for pnode in priv}
    existing = db.scalars(select(AdminPermission)).all()
    # 所有"受管节点"= 菜单树 + 特权节点；签名比对 key+name，结构中任一变化即重建
    managed_keys = {e[1] for e in expected} | priv_keys
    managed = {r.key: r for r in existing if r.key in managed_keys}
    sig_now = tuple(sorted((k, r.name or "") for k, r in managed.items()))
    want_names = {e[1]: e[0] for e in expected}
    want_names.update({pnode[1]: pnode[0] for pnode in priv})
    sig_want = tuple(sorted(want_names.items()))
    if sig_now == sig_want:
        return 0  # 幂等：结构一致，不动（id 稳定）

    changed = 0
    for r in managed.values():
        db.delete(r)
    db.flush()

    group_id: dict[str, int] = {}
    for name, key, _pk, sort, icon in expected:
        if key.startswith("group:"):
            row = AdminPermission(name=name, key=key, pid=0, type="menu", path="",
                                  icon=icon, sort=sort, status=1)
            db.add(row); db.flush()
            group_id[key] = row.id
            changed += 1
    for name, key, pk, sort, icon in expected:
        if key.startswith("group:"):
            continue
        db.add(AdminPermission(name=name, key=key, pid=group_id.get(pk, 0),
                               type="menu", path="", icon=icon, sort=sort, status=1))
        changed += 1
    # 特权/按钮节点挂到对应分组
    for name, key, gname, sort, icon, typ in priv:
        gkey = "group:" + gname
        db.add(AdminPermission(name=name, key=key, pid=group_id.get(gkey, 0),
                               type=typ, path="", icon=icon, sort=sort, status=1))
        changed += 1
    return changed


def seed_site(db: Session, cfg, seed_file: Path, force: bool = False) -> dict:
    """把站点专属 seed.json 幂等导入：按唯一键（slug / code / username）判重。"""
    if not seed_file.exists():
        return {"error": f"种子文件不存在: {seed_file}"}
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    result: dict[str, int] = {}

    # 管理员（幂等：存在则更新密码）
    # 敏感信息零入库：seed.json 中密码为占位符时回退到 cfg.admin_password（环境变量/本地凭据文件）
    username = data.get("admin", {}).get("username", cfg.admin_user)
    _seed_pwd = str(data.get("admin", {}).get("password") or "")
    password = cfg.admin_password if (not _seed_pwd or _seed_pwd.startswith("${")) else _seed_pwd
    admin = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if admin is None:
        db.add(AdminUser(username=username, password_hash=hash_password(password),
                         nickname=data.get("admin", {}).get("nickname", "管理员"), role="super"))
        result["admin"] = 1
    elif force:
        admin.password_hash = hash_password(password)
        result["admin"] = 1

    # 配置
    for key, value in (data.get("settings") or {}).items():
        row = db.scalar(select(Setting).where(Setting.key == key))
        if row is None:
            db.add(Setting(key=key, value=value if isinstance(value, str) else jdumps(value),
                           group="basic"))
            result["settings"] = result.get("settings", 0) + 1
        elif force:
            row.value = value if isinstance(value, str) else jdumps(value)

    # 内容模型（内置：文章/产品/案例/banner，按 code 幂等）
    # 字段定义：系统字段（sys=1，全部模型一致，顺序固定）+ 各模型扩展字段
    def _f(name, label, typ="text", required=0, list_=0, default="", options=None):
        d = {"name": name, "label": label, "type": typ, "required": required, "list": list_,
             "default": default, "sys": 0, "hidden": 0, "options": options or [], "sort": 0}
        return d

    def _sys(name, label, typ, required=0, list_=1):
        d = _f(name, label, typ, required, list_)
        d["sys"] = 1
        return d

    # 系统字段序列（字段管理可见可编辑，标识/类型固定）：sort 由保存时按顺序写入
    sys_fields = [
        _sys("title", "标题", "text", required=1),
        _sys("slug", "访问别名", "text"),
        _sys("category_id", "所属分类", "select"),
        _sys("cover", "封面图", "image_single"),
        _sys("publish_at", "发布时间", "datetime"),
        _sys("body", "正文内容", "editor", list_=0),
        _sys("is_top", "是否置顶", "switch", list_=0),
        _sys("is_hot", "是否热门", "switch", list_=0),
        _sys("status", "状态", "select"),
        _sys("seo_title", "seo标题", "text", list_=0),
        _sys("seo_keywords", "seo关键词", "tag", list_=0),
        _sys("seo_description", "seo描述", "textarea", list_=0),
        _sys("sort", "排序", "number", list_=0),
    ]

    # 模型中文名以 nanjing 站配置为基准（2026-11-20 需求：所有站按 nanjing 的入库配置对齐）
    builtin_models = [
        ("新闻", "article", "bi-file-earmark-text", [
            _f("author", "作者", "text", list_=1),
            _f("source", "来源", "text", list_=1),
            _f("reading_time", "阅读时长(分钟)", "number"),
        ]),
        ("项目", "product", "bi-box", [
            _f("price", "价格", "text", list_=1),
            _f("spec", "规格型号", "text", list_=1),
            _f("unit", "单位", "text"),
        ]),
        ("案例", "case", "bi-briefcase", [
            _f("client", "客户名称", "text", list_=1),
            _f("project_date", "项目时间", "text", list_=1),
            _f("industry", "所属行业", "text"),
        ]),
        ("页面", "page", "bi-file-earmark", [
            _f("sub_title", "副标题", "text", list_=1),
        ]),
        ("banner", "banner", "bi-images", [
            _f("sub_title", "副标题", "text", list_=1),
        ]),
    ]

    # 需求：banner 模型统一只保留 标题(title)/图片(cover)/副标题(sub_title)/状态(status) 四个字段 ——
    # 其余系统字段直接移除（不是隐藏），并移除旧版预置扩展字段（跳转链接/打开方式）
    SYS_OVERRIDES = {
        "banner": {
            "keep": {"title", "cover", "status"},
            "label": {"cover": "图片", "status": "状态"},
            "list": {"title": 1, "cover": 1, "sub_title": 1, "status": 1},
            "remove_preset": {"link_url", "target"},
        },
    }

    # 需求（2026-11-23）：除「页面」外，所有内容模型移除「访问别名(slug)」字段——
    # 表单/字段管理不再显示；保存时后端仍按标题自动生成 slug，前台 URL 不受影响。
    # 分类是独立资源（category 表），不在此列。
    SLUG_KEEP_CODES = {"page"}

    def _effective_sys_fields(code):
        """banner 等有字段覆盖的模型：系统字段直接裁剪到 keep 集合（字段管理中不再出现多余字段）。"""
        ov = SYS_OVERRIDES.get(code)
        fields = sys_fields
        if ov:
            fields = [s for s in fields if s["name"] in ov["keep"]]
        if code not in SLUG_KEEP_CODES:
            fields = [s for s in fields if s["name"] != "slug"]
        return fields

    def _apply_sys_overrides(fields, code):
        ov = SYS_OVERRIDES.get(code)
        if not ov:
            return fields
        keep = ov["keep"]
        preset_names = {x.get("name") for x in fields if isinstance(x, dict) and not x.get("sys")}
        out = []
        for x in fields:
            if not isinstance(x, dict):
                continue
            if x.get("name") in ov.get("remove_preset", ()):
                continue  # 移除旧预置扩展字段
            if x.get("sys") and x["name"] not in keep and x["name"] not in preset_names:
                continue  # 需求：多余系统字段直接移除，字段管理只显示保留的字段
            if x.get("name") in ov.get("label", {}):
                x = {**x, "label": ov["label"][x["name"]]}
            if x.get("name") in ov.get("list", {}):
                x = {**x, "list": ov["list"][x["name"]]}
            out.append(x)
        return out

    def _upgrade_preset(cur, preset_fields):
        """将预置扩展字段的 type/options/default 同步到已有字段定义（保留用户改的 label/required/list/hidden）。"""
        preset_map = {p["name"]: p for p in preset_fields}
        out = []
        for x in cur:
            if isinstance(x, dict) and x.get("name") in preset_map:
                p = preset_map[x["name"]]
                x = {**x, "type": p["type"], "options": p.get("options") or [],
                     "default": x.get("default") or p.get("default", "")}
            out.append(x)
        return out

    for name, code, icon, preset_fields in builtin_models:
        row_ct = db.scalar(select(ContentType).where(ContentType.code == code))
        if not row_ct:
            db.add(ContentType(name=name, code=code, icon=icon, status=1,
                               fields=jdumps(_apply_sys_overrides(_effective_sys_fields(code) + preset_fields, code))))
            result["content_type"] = result.get("content_type", 0) + 1
        else:
            # 模型中文名跟随内置基准（如 文章→新闻 / 产品→项目 / 单页→页面）
            if row_ct.name != name:
                row_ct.name = name
                result["content_type"] = result.get("content_type", 0) + 1
            # 幂等迁移：字段定义里还没有系统字段（V16 之前的旧结构）→ 重建为 系统字段 + 已有扩展字段
            try:
                cur = json.loads(row_ct.fields or "[]")
            except ValueError:
                cur = []
            if not isinstance(cur, list):
                cur = []
            has_sys = any(isinstance(x, dict) and x.get("sys") for x in cur)
            if not has_sys:
                row_ct.fields = jdumps(_apply_sys_overrides(_effective_sys_fields(code) + _upgrade_preset(cur, preset_fields), code))
                result["content_type_fields"] = result.get("content_type_fields", 0) + 1
            else:
                # 已有系统字段：升级预置扩展字段属性（如 target 改单选）+ 补齐缺失的系统字段
                cur = _upgrade_preset(cur, preset_fields)
                eff_sys = _effective_sys_fields(code)
                # 同步系统字段类型（cover image→image_single、seo_keywords text→tag 等预置变更）
                sys_preset = {s["name"]: s["type"] for s in eff_sys}
                for x in cur:
                    if isinstance(x, dict) and x.get("sys") and sys_preset.get(x.get("name")):
                        x["type"] = sys_preset[x["name"]]
                cur_names = {x.get("name") for x in cur if isinstance(x, dict)}
                miss = [s for s in eff_sys if s["name"] not in cur_names]
                if miss:
                    sys_pos = max((i for i, x in enumerate(cur) if isinstance(x, dict) and x.get("sys")), default=-1) + 1
                    cur = cur[:sys_pos] + miss + cur[sys_pos:]
                    result["content_type_fields"] = result.get("content_type_fields", 0) + 1
                new_cur = _apply_sys_overrides(cur, code)
                if new_cur != cur:
                    result["content_type_fields"] = result.get("content_type_fields", 0) + 1
                cur = new_cur
                row_ct.fields = jdumps(cur)

    # 需求：存量模型（含自定义模型）统一移除「访问别名(slug)」系统字段（页面模型保留，
    # 幂等：启动时执行，已移除的模型无变化）
    for row_ct in db.scalars(select(ContentType)).all():
        if row_ct.code in SLUG_KEEP_CODES:
            continue
        try:
            cur = json.loads(row_ct.fields or "[]")
        except ValueError:
            cur = []
        if not isinstance(cur, list):
            continue
        stripped = [x for x in cur
                    if not (isinstance(x, dict) and x.get("sys") and x.get("name") == "slug")]
        if len(stripped) != len(cur):
            row_ct.fields = jdumps(stripped)
            result["content_type_fields"] = result.get("content_type_fields", 0) + 1

    # 需求（2026-11-24）：修复历史数据——部分模型的「所属分类(category_id)」系统字段被误标为
    # hidden=1，导致后台发布表单没有分类下拉、前台按分类看不到文章。启动时幂等恢复显示。
    for row_ct in db.scalars(select(ContentType)).all():
        try:
            cur = json.loads(row_ct.fields or "[]")
        except ValueError:
            continue
        if not isinstance(cur, list):
            continue
        changed = False
        for x in cur:
            if isinstance(x, dict) and x.get("sys") and x.get("name") == "category_id" and x.get("hidden"):
                x["hidden"] = 0
                changed = True
        if changed:
            row_ct.fields = jdumps(cur)
            result["content_type_fields"] = result.get("content_type_fields", 0) + 1

    # 标签
    for tag in data.get("tags") or []:
        if not db.scalar(select(Tag).where(Tag.name == tag["name"])):
            db.add(Tag(**_fill(Tag, tag)))
            result["tags"] = result.get("tags", 0) + 1

    # 栏目（先建父级，再建子级）
    cat_ids: dict[str, int] = {}
    categories = data.get("categories") or []
    for item in sorted(categories, key=lambda x: x.get("pid", 0)):
        slug = item.get("slug", "")
        existing = db.scalar(select(Category).where(Category.slug == slug)) if slug else None
        if existing is None:
            payload = _fill(Category, item)
            parent_slug = item.pop("_parent", None)
            if parent_slug and parent_slug in cat_ids:
                payload["pid"] = cat_ids[parent_slug]
            row = Category(**payload)
            db.add(row)
            db.flush()
            cat_ids[slug] = row.id
            result["categories"] = result.get("categories", 0) + 1
        else:
            cat_ids[slug] = existing.id

    # 内容
    for item in data.get("contents") or []:
        title = item.get("title", "")
        existing = db.scalar(select(Content).where(Content.title == title)) if title else None
        if existing is None:
            payload = _fill(Content, item)
            cat_slug = item.get("category_slug", "")   # 非模型字段，需从原始数据取
            if cat_slug in cat_ids:
                payload["category_id"] = cat_ids[cat_slug]
            if payload.get("publish_at") == "now":
                payload["publish_at"] = datetime.now()
            if "tags" in payload and isinstance(payload["tags"], list):
                payload["tags"] = ",".join(payload["tags"])
            row = Content(**payload)
            db.add(row)
            result["contents"] = result.get("contents", 0) + 1

    # 表单模型
    for item in data.get("forms") or []:
        code = item.get("code", "")
        if not db.scalar(select(FormModel).where(FormModel.code == code)):
            payload = _fill(FormModel, item)
            if isinstance(payload.get("fields"), list):
                payload["fields"] = jdumps(payload["fields"])
            db.add(FormModel(**payload))
            result["forms"] = result.get("forms", 0) + 1

    # 角色（幂等创建；rules 跟随新菜单 key 对齐更新）
    roles = [
        ("超级管理员", ["*"]),
        ("内容编辑", ["dashboard", "content-article", "content-product", "content-case",
                      "content-category", "content-banner", "content-page", "media"]),
        ("运营专员", ["dashboard", "member-list", "order-list", "comment", "form-record"]),
    ]
    for name, rules in roles:
        role = db.scalar(select(AdminRole).where(AdminRole.name == name))
        if role is None:
            db.add(AdminRole(name=name, rules=jdumps(rules), site_ids="[]", status=1))
            result["roles"] = result.get("roles", 0) + 1
        elif role.rules != jdumps(rules):
            role.rules = jdumps(rules)  # 对齐新菜单 key

    # 权限节点：按新菜单结构对齐（分组+菜单项），button 类保留并重新挂载
    result["permissions"] = result.get("permissions", 0) + _align_permission_tree(db)

    db.commit()
    return result
