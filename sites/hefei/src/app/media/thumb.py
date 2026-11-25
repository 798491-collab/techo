"""按访问参数处理单张图片，并缓存结果。

首页和列表页的地址仍是原图，只在后面加上处理参数，例如：
/uploads/a.jpg?x-oss-process=image/auto-orient,1/resize,m_fill,w_520,h_400/quality,q_80/format,webp

宽高由各主题模板按样式传入。浏览器请求到哪张，就只处理哪张。
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from urllib.parse import quote

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

def oss(url, width, height, mode="fill") -> str:
    """按主题样式给出的宽高生成处理参数。占位图和外链保持原样。

    mode: fill=裁满(默认) lfit=限定框内完整显示(logo 用) fixed=拉伸
    """
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return url or ""
    if w < 1 or h < 1:
        return url or ""
    if mode not in ("fill", "lfit", "fixed"):
        mode = "fill"
    return with_process(url, f"image/auto-orient,1/resize,m_{mode},w_{w},h_{h}/quality,q_80/format,webp")

_RASTER = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_FORMATS = {"webp": ("WEBP", "image/webp"), "jpg": ("JPEG", "image/jpeg"), "jpeg": ("JPEG", "image/jpeg"), "png": ("PNG", "image/png")}
_MAX_EDGE = 4096
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def with_process(url: str, process: str) -> str:
    """给上传图片地址补上 x-oss-process。占位图、外链、矢量图保持原样。"""
    if not url or not isinstance(url, str) or not process:
        return url or ""
    if "x-oss-process=" in url:
        return url
    path = url.split("?", 1)[0]
    if not path.startswith("/uploads/"):
        return url
    rel = path[len("/uploads/"):]
    if not rel or Path(rel).suffix.lower() not in _RASTER:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}x-oss-process={quote(process, safe='/,_')}"


def rewrite_items(items, field: str = "cover", process: str = ""):
    if not items:
        return items
    return [rewrite_one(item, field, process) for item in items]


def rewrite_one(item: dict, field: str = "cover", process: str = "") -> dict:
    if not isinstance(item, dict):
        return item
    current = item.get(field) or ""
    new = with_process(current, process)
    if not new or new == current:
        return item
    copied = dict(item)
    copied[field] = new
    return copied


def cached_process(uploads: Path, cache_dir: Path, rel: str, process: str) -> tuple[Path, str] | None:
    """处理这一张图并返回缓存文件。已有且原图未变时直接复用。失败返回 None。"""
    if Image is None:
        return None
    spec = _parse(process)
    src = _under(uploads, rel)
    if spec is None or src is None:
        return None
    dest, stamp_path, media = _cache_paths(cache_dir, rel, process, spec["format"])
    token = _stamp(src)
    if _fresh(dest, stamp_path, token):
        return dest, media
    lock = _lock_for(str(dest))
    with lock:
        token = _stamp(src)
        if _fresh(dest, stamp_path, token):
            return dest, media
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            _write(src, tmp, spec)
        except Exception:
            tmp.unlink(missing_ok=True)
            if spec.get("format") == "webp":
                spec = dict(spec)
                spec["format"] = "jpg"
                dest, stamp_path, media = _cache_paths(cache_dir, rel, process, "jpg")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".tmp")
                try:
                    _write(src, tmp, spec)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    return None
            else:
                return None
        tmp.replace(dest)
        stamp_path.write_text(token, encoding="utf-8")
    return (dest, media) if dest.is_file() else None


def _parse(process: str) -> dict | None:
    text = (process or "").strip()
    if not text.startswith("image/") and text != "image":
        return None
    spec = {"orient": False, "mode": "lfit", "w": 0, "h": 0, "quality": 80, "format": "webp"}
    for part in text.split("/"):
        bits = [b for b in part.split(",") if b]
        if not bits or bits[0] == "image":
            continue
        name = bits[0]
        if name == "auto-orient":
            spec["orient"] = (bits[1] if len(bits) > 1 else "1") != "0"
        elif name == "resize":
            for bit in bits[1:]:
                if bit.startswith("m_"):
                    spec["mode"] = bit[2:]
                elif bit.startswith("w_") and bit[2:].isdigit():
                    spec["w"] = int(bit[2:])
                elif bit.startswith("h_") and bit[2:].isdigit():
                    spec["h"] = int(bit[2:])
        elif name == "quality":
            for bit in bits[1:]:
                if bit.startswith("q_") and bit[2:].isdigit():
                    spec["quality"] = int(bit[2:])
        elif name == "format" and len(bits) > 1:
            spec["format"] = bits[1].lower()
    if spec["w"] <= 0 and spec["h"] <= 0:
        return None
    if spec["w"] < 0 or spec["h"] < 0 or spec["w"] > _MAX_EDGE or spec["h"] > _MAX_EDGE:
        return None
    if spec["format"] not in _FORMATS:
        return None
    spec["quality"] = min(100, max(1, spec["quality"]))
    return spec


def _cache_paths(cache_dir: Path, rel: str, process: str, fmt: str) -> tuple[Path, Path, str]:
    save_fmt, media = _FORMATS[fmt]
    digest = hashlib.sha1(f"{rel}\n{process}".encode("utf-8")).hexdigest()
    ext = "jpg" if save_fmt == "JPEG" else fmt
    dest = cache_dir / "oss" / digest[:2] / f"{digest}.{ext}"
    return dest, Path(str(dest) + ".stamp"), media


def _write(src: Path, dest: Path, spec: dict) -> None:
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            im.seek(0)
        frame = ImageOps.exif_transpose(im) if spec["orient"] else im
        frame = frame or im
        frame = _resize(frame, spec["mode"], spec["w"], spec["h"], resample)
        save_fmt, _media = _FORMATS[spec["format"]]
        if save_fmt == "JPEG" or frame.mode not in ("RGB", "RGBA"):
            if frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info):
                frame = frame.convert("RGBA") if save_fmt != "JPEG" else _flatten(frame)
            else:
                frame = frame.convert("RGB")
        elif frame.mode == "P":
            frame = frame.convert("RGBA")
        kwargs = {}
        if save_fmt in ("WEBP", "JPEG"):
            kwargs["quality"] = spec["quality"]
        if save_fmt == "WEBP":
            kwargs["method"] = 4
        frame.save(dest, format=save_fmt, **kwargs)


def _resize(frame, mode: str, width: int, height: int, resample):
    sw, sh = frame.size
    if sw < 1 or sh < 1:
        return frame
    if mode == "fill" and width > 0 and height > 0:
        scale = max(width / sw, height / sh)
        nw, nh = max(width, round(sw * scale)), max(height, round(sh * scale))
        frame = frame.resize((nw, nh), resample)
        left = max(0, (nw - width) // 2)
        top = max(0, (nh - height) // 2)
        return frame.crop((left, top, left + width, top + height))
    if mode == "fixed" and width > 0 and height > 0:
        return frame.resize((width, height), resample)
    box_w = width or sw
    box_h = height or sh
    scale = min(box_w / sw, box_h / sh)
    if scale <= 0:
        return frame
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    return frame.resize((nw, nh), resample)


def _flatten(frame):
    base = Image.new("RGB", frame.size, (255, 255, 255))
    base.paste(frame.convert("RGBA"), mask=frame.convert("RGBA").split()[-1])
    return base


def _stamp(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _under(base: Path, rel: str) -> Path | None:
    if not rel or "\\" in rel or rel.endswith("/"):
        return None
    root = base.resolve()
    target = (root / rel).resolve()
    if target != root and not str(target).startswith(str(root) + "\\") and not str(target).startswith(str(root) + "/"):
        return None
    if not target.is_file():
        return None
    return target


def _fresh(dest: Path, stamp_path: Path, token: str) -> bool:
    if not dest.is_file() or not stamp_path.is_file():
        return False
    try:
        return stamp_path.read_text(encoding="utf-8").strip() == token
    except OSError:
        return False


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock
