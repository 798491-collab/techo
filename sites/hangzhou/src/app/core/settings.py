"""站点配置。

.env.example 放端口和目录等非敏感配置，密钥只放 .env（或环境变量）。
.env 放 SECRET_KEY、ADMIN_PASSWORD，不进 Git。
导航、轮播、数字和任何 URL 都不写在这里。
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[3]
THEMES_ROOT = SITE_ROOT / "themes"
THEMES_MACROS = THEMES_ROOT / "macros"
ADMIN_DIR = SITE_ROOT / "admin"


def _parse_toml(text: str) -> dict:
    """只解析本项目使用的扁平 TOML：key = 字符串或整数。"""
    data: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"'):
            data[key] = json.loads(value)
        elif value.startswith("'") and value.endswith("'"):
            data[key] = value[1:-1]
        else:
            try:
                data[key] = int(value)
            except ValueError:
                data[key] = value
    return data


def _ensure_dotenv(path: Path) -> None:
    """首次启动自动生成 .env：密钥落盘一次后固定，不做内存兜底。

    已有非空值绝不覆盖；缺失或空值才生成，初始密码打印一次供保存。
    老部署升级时先从 runtime/.secrets.json 迁移密钥，保住已有登录态。
    """
    import secrets
    # 老部署：旧脚本可能未生成 .env，但 runtime/.secrets.json 里有真实密钥
    if not path.is_file():
        legacy = path.parent / "runtime" / ".secrets.json"
        if legacy.is_file():
            try:
                import json as _json
                sec = _json.loads(legacy.read_text(encoding="utf-8") or "{}") or {}
                lines = []
                if sec.get("secret"):
                    lines.append("SECRET_KEY=" + _json.dumps(sec["secret"], ensure_ascii=False))
                if sec.get("admin_password"):
                    lines.append("ADMIN_PASSWORD=" + _json.dumps(sec["admin_password"], ensure_ascii=False))
                if lines:
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except (ValueError, OSError):
                pass
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept: list[str] = []
    values: dict[str, str] = {}
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            kept.append(raw)
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in ("SECRET_KEY", "ADMIN_PASSWORD") and not v.strip('"').strip("'"):
            continue  # 空值视为缺失，下面重新生成
        values[k] = v
        kept.append(raw)

    generated: list[str] = []
    if not values.get("SECRET_KEY") and not (os.environ.get("SECRET_KEY") or os.environ.get("PYSITE_SECRET")):
        values["SECRET_KEY"] = secrets.token_hex(32)
        generated.append("SECRET_KEY")
    pwd: str | None = None
    if not values.get("ADMIN_PASSWORD") and not (os.environ.get("ADMIN_PASSWORD") or os.environ.get("PYSITE_ADMIN_PASSWORD")):
        pwd = secrets.token_urlsafe(18)
        values["ADMIN_PASSWORD"] = pwd
        generated.append("ADMIN_PASSWORD")
    if not generated and path.is_file():
        return

    if not kept:
        kept = [
            "# 本站点密钥（首次启动自动生成；删除后重启会重新生成，登录态与后台密码都会变）",
            "# 此文件不进 Git，请妥善备份",
        ]
    kept = [ln for ln in kept if not ln.startswith("# 启动时自动补齐")]
    if generated:
        kept.append("# 启动时自动补齐的缺失密钥")
        for k in generated:
            kept.append(f"{k}={values[k]}")
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if pwd:
        print(f"[初始化] {path.name} 后台初始密码: {pwd}（请保存）")
    else:
        print(f"[初始化] 已生成 {path.name}")


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = json.loads(value) if value[0] == '"' else value[1:-1]
        os.environ.setdefault(key, value)


def _copy_missing(src_dir: Path, dest_dir: Path) -> None:
    if not src_dir.is_dir():
        return
    for src in src_dir.rglob("*"):
        if not src.is_file() or src.name == ".gitkeep":
            continue
        dest = dest_dir / src.relative_to(src_dir)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _copy_db(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    src_conn = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _migrate_legacy(root: Path) -> None:
    """把旧目录（data / runtime / var / uploads）的生产数据一次性迁到 storage，不删旧文件。

    容器化后 storage 是唯一的持久化卷；老部署升级时旧目录里的数据不能丢。
    """
    if os.environ.get("PYSITE_DB"):
        return
    storage = root / "storage"
    new_db = storage / "site.db"
    if not new_db.exists():
        candidates = [p for p in (
            root / "data" / "site.db", root / "runtime" / "site.db", root / "var" / "site.db",
        ) if p.is_file()]
        if candidates:
            src = max(candidates, key=lambda p: p.stat().st_mtime)
            try:
                _copy_db(src, new_db)
            except Exception:
                shutil.copy2(src, new_db)
    _copy_missing(root / "uploads", storage / "uploads")
    _copy_missing(root / "runtime" / "uploads", storage / "uploads")
    _copy_missing(root / "data" / "uploads", storage / "uploads")
    for old in ("data", "runtime"):
        for d in ("logs", "cache", "sessions", "temp"):
            _copy_missing(root / old / d, storage / d)
    for d in ("logs", "cache", "sessions"):
        _copy_missing(root / "var" / d, storage / d)
    _copy_missing(root / "var" / "tmp", storage / "temp")
    # seed.json 是入库文件，但旧部署脚本可能把整个 storage 目录当旧目录删掉；
    # 若新卷里缺失，从旧 data 目录补回，保证首次建库 / 重新播种不失败。
    new_seed = storage / "seed.json"
    if not new_seed.exists():
        for cand in (root / "data" / "seed.json", root / "seed.json"):
            if cand.is_file():
                try:
                    storage.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cand, new_seed)
                except OSError:
                    pass
                break


@dataclass
class Settings:
    """应用级配置（.env.example）。
    站点内容信息（名称/联系方式/SEO 等）一律存数据库 Setting 表（后台基础设置/SEO 配置维护），
    本配置文件只保留应用运行所需字段。"""
    key: str
    port: int
    name: str = ""          # 兼容旧字段：仅作兜底，站点名以后台 site_name 为准
    short_name: str = ""
    tagline: str = ""
    city: str = ""
    industry: str = ""
    phone: str = ""
    mobile: str = ""
    email: str = ""
    address: str = ""
    icp: str = ""
    gongan_icp: str = ""
    keywords: str = ""
    description: str = ""
    copyright: str = ""
    db_path: str = "storage/site.db"
    cache_dir: str = "storage/cache"
    upload_dir: str = "storage/uploads"
    theme_dir: str = "themes"
    log_rel: str = "storage/logs"
    tmp_dir: str = "storage/temp"
    session_rel: str = "storage/sessions"
    admin_user: str = "admin"
    secret: str = ""
    admin_password: str = "admin"
    theme: str = "default"

    @property
    def root(self) -> Path:
        return SITE_ROOT

    def _abs(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    @property
    def theme_root(self) -> Path:
        return self._abs(self.theme_dir)

    @property
    def templates_dir(self) -> Path:
        return self.theme_root / "default" / "templates"

    @property
    def static_dir(self) -> Path:
        return self.theme_root / "default" / "static"

    @property
    def db_file(self) -> Path:
        override = os.environ.get("PYSITE_DB")
        if override:
            return Path(override)
        return self._abs(self.db_path)

    @property
    def cache_path(self) -> Path:
        override = os.environ.get("PYSITE_CACHE")
        if override:
            return Path(override)
        return self._abs(self.cache_dir)

    @property
    def uploads_path(self) -> Path:
        override = os.environ.get("PYSITE_UPLOAD")
        if override:
            return Path(override)
        return self._abs(self.upload_dir)

    @property
    def log_dir(self) -> Path:
        return self._abs(self.log_rel)

    @property
    def log_path(self) -> Path:
        return self.log_dir

    @property
    def temp_dir(self) -> Path:
        return self._abs(self.tmp_dir)

    @property
    def session_dir(self) -> Path:
        return self._abs(self.session_rel)

    @property
    def session_path(self) -> Path:
        return self.session_dir

    def ensure_dirs(self) -> None:
        for path in (
            self.cache_path, self.uploads_path, self.db_file.parent,
            self.log_path, self.temp_dir, self.session_path,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    _migrate_legacy(SITE_ROOT)
    _ensure_dotenv(SITE_ROOT / ".env")
    _load_dotenv(SITE_ROOT / ".env")
    path = SITE_ROOT / ".env.example"
    if not path.is_file():
        raise FileNotFoundError(f"站点配置不存在: {path}")
    data = _parse_toml(path.read_text(encoding="utf-8"))
    data.setdefault("key", SITE_ROOT.name)
    data["port"] = int(data.get("port") or 0)
    if "log_dir" in data:
        data["log_rel"] = data.pop("log_dir")
    if "session_dir" in data:
        data["session_rel"] = data.pop("session_dir")

    # 密钥只从 .env（或环境变量）读取，不再兜底 .secrets.json / 随机生成。
    # 缺少 SECRET_KEY 直接报错，避免每次重启换密钥导致登录态失效。
    secret = os.environ.get("SECRET_KEY") or os.environ.get("PYSITE_SECRET")
    if not secret:
        raise RuntimeError(
            f"站点 {SITE_ROOT.name} 缺少 SECRET_KEY：请在站点根目录 .env 中配置 SECRET_KEY"
        )
    password = os.environ.get("ADMIN_PASSWORD") or os.environ.get("PYSITE_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError(
            f"站点 {SITE_ROOT.name} 缺少 ADMIN_PASSWORD：请在站点根目录 .env 中配置 ADMIN_PASSWORD"
        )
    known = {f.name for f in Settings.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    payload = {k: v for k, v in data.items() if k in known}
    payload["secret"] = secret
    payload["admin_password"] = password
    cfg = Settings(**payload)
    cfg.ensure_dirs()
    return cfg


# 旧名字，供搬迁后的模块继续引用。
SiteConfig = Settings
load_site = load_settings
