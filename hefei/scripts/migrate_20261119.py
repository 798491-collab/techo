"""一次性数据迁移（2026-11-19 需求）：

1. 顶部菜单：资质服务/服务领域/咨询服务 → 服务项目（产品栏目），人才注册/人才服务 → 精选案例（案例栏目）
2. 服务项目（产品）栏目挂二级子栏目（人才注册、安全生产许可、资质转让收购），前台出二级菜单
3. 案例栏目统一命名「精选案例」并设为导航项
4. nanjing 已有的 guest_book 表单：需要回复(单选) 补选项配置（是/否）

幂等：重复执行安全。执行后建议清空各站点 cache 目录（脚本已处理）。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[2]
SITES = ["nanjing", "hefei", "xuzhou", "wuxi", "hangzhou"]

GUEST_BOOK_FIELDS = [
    {"label": "姓名", "field": "name", "type": "text", "required": 1, "default": "", "options": []},
    {"label": "手机号码", "field": "phone", "type": "text", "required": 1, "default": "", "options": []},
    {"label": "公司", "field": "company", "type": "text", "required": 0, "default": "", "options": []},
    {"label": "内容", "field": "content", "type": "textarea", "required": 0, "default": "", "options": []},
    {"label": "需要回复", "field": "need_reply", "type": "radio", "required": 0, "default": "否",
     "options": [{"label": "是", "value": "是"}, {"label": "否", "value": "否"}]},
]


def migrate_site(key: str) -> None:
    db_file = SITE_ROOT / key / "data" / "site.db"
    if not db_file.exists():
        print(f"[{key}] 数据库不存在，跳过")
        return
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        # need_login 列：若站点尚未重启过（_migrate 未执行），这里直接补列
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(form_model)")}
        if cols and "need_login" not in cols:
            conn.execute("ALTER TABLE form_model ADD COLUMN need_login INTEGER DEFAULT 0")
            conn.commit()
        rows = [dict(r) for r in conn.execute(
            "select id,name,slug,model,pid,is_nav,sort from category where deleted_at is null")]

        def by(pred):
            return [r for r in rows if pred(r)]

        product_top = next((r for r in by(lambda r: r["model"] == "product" and r["pid"] == 0 and r["is_nav"] == 1)), None)
        changes = []

        # 1. 产品顶级栏目 → 服务项目
        if product_top and product_top["name"] != "服务项目":
            conn.execute("update category set name='服务项目' where id=?", (product_top["id"],))
            changes.append(f"栏目#{product_top['id']} {product_top['name']} → 服务项目")

        # 2. 案例栏目 → 精选案例（导航）：优先 slug=case；站点没有 case 栏目时用 anli 作导航，其余保持非导航
        case_cats = by(lambda r: r["model"] == "case" and r["slug"] in ("case", "anli"))
        nav_slug = "case" if any(r["slug"] == "case" for r in case_cats) else "anli"
        for r in case_cats:
            is_nav_slug = r["slug"] == nav_slug
            want_nav = 1 if is_nav_slug else 0
            want_name = "精选案例" if is_nav_slug else "案例展示"
            want_sort = 3 if is_nav_slug else 8
            if r["name"] != want_name or r["is_nav"] != want_nav or r["sort"] != want_sort:
                conn.execute("update category set name=?, is_nav=?, sort=? where id=?",
                             (want_name, want_nav, want_sort, r["id"]))
                changes.append(f"栏目#{r['id']} {r['name']} → {want_name}({'导航' if want_nav else '非导航'})")

        # 3. 人才注册/人才服务 挂到 服务项目 下（二级菜单），不再占顶级导航
        if product_top:
            for r in by(lambda r: r["slug"] in ("rencai", "talent") and r["pid"] == 0):
                if r["id"] == product_top["id"]:
                    continue
                if r["pid"] != product_top["id"] or r["is_nav"] != 0:
                    conn.execute("update category set pid=?, is_nav=0, sort=30 where id=?",
                                 (product_top["id"], r["id"]))
                    changes.append(f"栏目#{r['id']} {r['name']} → 服务项目子栏目")
            # 4. 其余产品类顶级栏目（安全生产许可/资质转让收购）同样挂为子栏目（先刷新行缓存）
            rows = [dict(r) for r in conn.execute(
                "select id,name,slug,model,pid,is_nav,sort from category where deleted_at is null")]
            for r in by(lambda r: r["model"] == "product" and r["pid"] == 0 and r["id"] != product_top["id"]):
                conn.execute("update category set pid=?, is_nav=0, sort=31 where id=?",
                             (product_top["id"], r["id"]))
                changes.append(f"栏目#{r['id']} {r['name']} → 服务项目子栏目")

        # 5. 导航排序：关于 1 / 服务项目 2 / 精选案例 3 / 新闻 4 / 联系 5
        sort_map = {"about": 1, "news": 4, "contact": 5}
        for slug, sort in sort_map.items():
            for r in by(lambda x, s=slug: x["slug"] == s):
                if r["sort"] != sort:
                    conn.execute("update category set sort=? where id=?", (sort, r["id"]))
        if product_top:
            conn.execute("update category set sort=2 where id=?", (product_top["id"],))

        # 6. guest_book 表单：补齐字段定义与 need_reply 选项
        row = conn.execute("select id,fields from form_model where code='guest_book' and deleted_at is null").fetchone()
        if row is None:
            conn.execute(
                "insert into form_model (site_id,name,code,fields,is_notify,notify_email,need_login,status,"
                "created_at,updated_at) values (0,'在线留言','guest_book',?,0,'',0,1,datetime('now','localtime'),"
                "datetime('now','localtime'))",
                (json.dumps(GUEST_BOOK_FIELDS, ensure_ascii=False),))
            changes.append("新增内置表单模型 guest_book 在线留言")
        else:
            try:
                fields = json.loads(row["fields"] or "[]")
            except ValueError:
                fields = []
            norm = []
            dirty = False
            for want in GUEST_BOOK_FIELDS:
                cur = next((f for f in fields if (f.get("field") or f.get("name")) == want["field"]), None)
                if cur is None:
                    norm.append(want)
                    dirty = True
                    continue
                f = {**cur, "field": want["field"], "label": cur.get("label") or want["label"],
                     "type": cur.get("type") or want["type"]}
                if want["options"] and not f.get("options"):
                    f["options"] = want["options"]
                    dirty = True
                if f.get("required") is None:
                    f["required"] = want["required"]
                    dirty = True
                norm.append(f)
            if dirty:
                conn.execute("update form_model set fields=? where id=?",
                             (json.dumps(norm, ensure_ascii=False), row["id"]))
                changes.append("guest_book 字段/选项补齐")

        conn.commit()
        print(f"[{key}] " + ("；".join(changes) if changes else "无变化"))
    finally:
        conn.close()

    # 清空文件缓存（栏目/首页数据缓存）
    cache_dir = SITE_ROOT / key / "cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    for key in (sys.argv[1:] or SITES):
        migrate_site(key)
    print("迁移完成")
