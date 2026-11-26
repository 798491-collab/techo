"""共用后台 API 路由对象：五站共用 /api/admin 前缀。

在这里挂全局 RBAC 守卫：菜单由 /menu 按角色 rules 精确下发；
本守卫再对数据/配置接口做二次校验，避免直接调接口绕过菜单权限。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.database import Content
from app.core.security import parse_token
from app.content.service import rule_allows, rules_for_user

# 无需功能权限、只需登录态的接口（登录/菜单/个人资料等）
PUBLIC_PATHS = {
    "/api/admin/captcha", "/api/admin/login", "/api/admin/logout", "/api/admin/me",
    "/api/admin/password-rule", "/api/admin/password", "/api/admin/menu",
    "/api/admin/cache/clear", "/api/admin/icon-options",
    "/api/admin/profile", "/api/admin/profile/logs",
}

# 各设置类页面共用 /settings 接口，按任一已授权设置项放行
SETTING_KEYS = [
    "setting-basic", "setting-switch", "setting-security", "setting-upload",
    "setting-sms", "setting-email", "setting-lang", "setting-lang-package",
    "station-setting", "order-pay-setting", "tool-seo",
]

PATH_RULES = {
    "/api/admin/settings": SETTING_KEYS,
    "/api/admin/reseed": ["setting-basic"],
    "/api/admin/backup/create": ["setting-basic"],
    "/api/admin/dashboard": ["dashboard"],
    "/api/admin/health": ["dev-health"],
    "/api/admin/perm-tree": ["auth-role", "auth-permission"],
    "/api/admin/email/test": ["setting-email"],
    "/api/admin/upload": ["media"],
    "/api/admin/files": ["media"],
    "/api/admin/station/sync": ["station-sync"],
    "/api/admin/station/generate": ["station-generate"],
    "/api/admin/plugins": ["dev-plugin"],
    "/api/admin/plugins/action": ["dev-plugin"],
    "/api/admin/plugins/config": ["dev-plugin"],
    "/api/admin/themes": ["dev-theme"],
    "/api/admin/themes/active": ["dev-theme"],
    "/api/admin/openapi/list": ["dev-openapi"],
    "/api/admin/openapi/save": ["dev-openapi"],
    "/api/admin/openapi/regen": ["dev-openapi"],
    "/api/admin/openapi/delete": ["dev-openapi"],
    "/api/admin/cron/list": ["tool-task", "tool-task-log"],
    "/api/admin/cron/save": ["tool-task"],
    "/api/admin/cron/toggle": ["tool-task"],
    "/api/admin/cron/delete": ["tool-task"],
    "/api/admin/cron/run": ["tool-task"],
    "/api/admin/cron/logs": ["tool-task", "tool-task-log"],
    "/api/admin/content-model/list": ["dev-content-model"],
    "/api/admin/content-model/save": ["dev-content-model"],
    "/api/admin/content-model/delete": ["dev-content-model"],
    "/api/admin/content-model/fields": ["dev-content-model"],
    "/api/admin/content-model/save-fields": ["dev-content-model"],
}

# 通用 CRUD 资源 -> 菜单 key（content 走动态模型 key，见 _required_keys）
RESOURCE_RULES = {
    "site": ["station-site"], "region": ["station-region"], "site_sync_log": ["station-sync"],
    "category": ["content-category"], "media": ["media"],
    "member": ["member-list"], "member_group": ["member-group"], "member_level": ["member-level"],
    "member_balance_log": ["member-balance-log"], "member_point_log": ["member-point-log"],
    "order": ["order-list"], "order_refund": ["order-refund"],
    "form_model": ["form-model"], "form_record": ["form-record"], "comment": ["comment"],
    "admin_task": ["tool-task"], "admin_task_log": ["tool-task-log"],
    "admin_user": ["auth-admin-user"], "admin_role": ["auth-role"],
    "admin_permission": ["auth-permission"], "operation_log": ["setting-log"],
    "lang": ["setting-lang"], "lang_package": ["setting-lang-package"],
    "content_type": ["dev-content-model"], "api_consumer": ["dev-openapi"],
}
CONTENT_SENTINEL = "__content__"
CRUD_PREFIXES = (
    "/api/admin/list/", "/api/admin/detail/", "/api/admin/save/",
    "/api/admin/delete/", "/api/admin/restore/",
)


def _required_keys(request: Request, path: str):
    if path in PUBLIC_PATHS:
        return None
    if path == "/api/admin/crud/config":
        key = (request.query_params.get("key") or "").strip()
        return [key] if key else None
    for prefix in CRUD_PREFIXES:
        if path.startswith(prefix):
            resource = path[len(prefix):].strip("/")
            if resource == "content":
                return [CONTENT_SENTINEL]
            return RESOURCE_RULES.get(resource)
    if path.startswith("/api/admin/ai/"):
        # AI 写作：授予任一内容模型权限或 AI 节点即可使用
        return ["ai.plugin", "ai.add", CONTENT_SENTINEL]
    return PATH_RULES.get(path)


async def admin_rbac_guard(request: Request):
    """全局后台权限守卫：仅校验已映射接口，未映射接口沿用原登录态逻辑。"""
    path = request.url.path.rstrip("/") or "/"
    if not path.startswith("/api/admin/") or path in PUBLIC_PATHS:
        return None
    cfg = request.app.state.cfg
    auth = request.headers.get("Authorization", "").strip()
    token = (auth[7:] if auth.startswith("Bearer ") else auth).strip() or request.cookies.get("cms_token", "")
    username = parse_token(cfg.secret, token) if token else ""
    if not username:
        return None  # 由各接口 current_admin 统一返回 401
    session = request.app.state.db.session()
    try:
        rules = rules_for_user(session, username)
        if not rules or rule_allows(rules, "*"):
            return None
        required = _required_keys(request, path)

        def content_model_key(model):
            return [f"content-{model}"] if model else [CONTENT_SENTINEL]

        # 内容类接口细化到模型：content-product 不授权 content-article
        if path.startswith("/api/admin/list/content"):
            required = content_model_key(request.query_params.get("model"))
        elif path.startswith("/api/admin/detail/content/"):
            try:
                row = session.get(Content, int(path.rsplit("/", 1)[-1]))
            except (ValueError, TypeError):
                row = None
            required = content_model_key(getattr(row, "model", ""))
        elif path in ("/api/admin/save/content", "/api/admin/delete/content", "/api/admin/restore/content"):
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            model = payload.get("model") or payload.get("content_model") or ""
            if not model:
                ids = payload.get("ids") or payload.get("id") or []
                if not isinstance(ids, list):
                    ids = [ids]
                for raw_id in ids[:1]:
                    try:
                        row = session.get(Content, int(raw_id))
                    except (ValueError, TypeError):
                        row = None
                    model = getattr(row, "model", "")
            required = content_model_key(model)
    finally:
        session.close()
    if not required:
        return None
    for key in required:
        if key == CONTENT_SENTINEL:
            if any(str(r).startswith("content-") for r in rules) or rule_allows(rules, "group:内容管理", "内容管理"):
                return None
        elif rule_allows(rules, key):
            return None
    raise HTTPException(status_code=403, detail={"code": 10003, "msg": "无权限访问该功能"})


router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_rbac_guard)])
