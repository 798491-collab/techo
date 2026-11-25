#!/usr/bin/env python3
"""2026-11-20 全站配置与数据对齐（幂等，可重复执行）。

需求来源：以 nanjing 站后台配置好的 数据模型/表单模型 为全站基准。
1. content_type：模型中文名 + fields 全量对齐 nanjing 基准
2. form_model：guest_book / consult 字段配置对齐 nanjing 基准
3. 产品分类只保留一个：product 子分类内容迁移到主分类，子分类软删
4. 数据量下限：case>=6、article>=10、product>=10（不足则补，参考 nanjing 标题风格）
5. 所有 article/product/case/page 必须有图（可重复），无图自动补
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[2]   # site/
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# nanjing 基准：模型中文名（fields 从 nanjing/storage/site.db 导出）
MODEL_NAMES = {"article": "新闻", "product": "项目", "case": "案例", "banner": "banner", "page": "页面"}

BASE_FORMS = {
    "guest_book": {
        "name": "在线留言", "code": "guest_book", "status": 1, "need_login": 0,
        "fields": [
            {"label": "姓名", "field": "name", "type": "text", "required": 1},
            {"label": "手机号码", "field": "phone", "type": "text", "required": 1},
            {"label": "公司", "field": "company", "type": "text", "required": 0},
            {"label": "内容", "field": "content", "type": "textarea", "required": 0},
            {"label": "需要回复", "field": "need_reply", "type": "radio", "required": 0,
             "options": [{"label": "是", "value": "是"}, {"label": "否", "value": "否"}]},
        ],
    },
    "consult": {
        "name": "在线咨询", "code": "consult", "status": 1, "need_login": 0,
        "fields": [
            {"label": "姓名", "name": "name", "type": "text", "required": True},
            {"label": "电话", "name": "phone", "type": "text", "required": True},
            {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
        ],
    },
}

# 数据量下限与补数据模板（按站点名称微调）
MIN_COUNTS = {"case": 6, "article": 10, "product": 10}

CASE_TEMPLATES = [
    ("某建设集团施工总承包一级资质升级成功案例",
     "协助企业完成人员配置、业绩梳理与申报材料编制，顺利通过评审取得施工总承包一级资质。",
     "<p>某建设集团原有施工总承包二级资质，因业务扩张需要升级为一级。我们为其制定了完整的人员补齐方案与业绩佐证材料清单，协助企业完成近五年代表业绩的梳理与四库一平台数据核验，全程跟踪评审进度，顺利取得施工总承包一级资质证书。</p>"),
    ("某建筑装饰公司专业承包资质新办成功案例",
     "从工商注册到资质落地的全流程代办，帮助企业快速取得建筑装修装饰专业承包资质。",
     "<p>某建筑装饰工程有限公司新成立，计划承接写字楼、商业空间装修项目，急需建筑装修装饰专业承包资质。我们为其提供从人员配置、社保开户到申报提交的全流程服务，企业以最小成本快速拿到资质证书，顺利中标首个装修项目。</p>"),
    ("某市政工程公司安全生产许可证延期成功案例",
     "提前规划安证延期材料，帮助企业完成三类人员继续教育与特种作业人员配置，按期完成延期。",
     "<p>某市政工程有限公司安全生产许可证即将到期，因三类人员证书临期面临延期受阻风险。我们提前两个月介入，协助企业完成安全员A/B/C证继续教育、特种作业人员配置与制度文件梳理，按期顺利完成安全生产许可证延期。</p>"),
    ("某劳务公司施工劳务资质备案成功案例",
     "协助企业完成施工劳务资质备案，技术工人证书配置齐全，快速承接劳务分包业务。",
     "<p>某建筑劳务有限公司需要施工劳务资质备案以承接劳务分包业务。我们协助企业完成技术工人证书配置、技术负责人任职材料准备，一次性通过备案审核，企业当月即承接了首个劳务分包项目。</p>"),
    ("某房地产公司开发资质延续成功案例",
     "协助企业完成房地产开发资质延续申报，专业人员配置与业绩材料全程指导。",
     "<p>某房地产开发有限公司资质证书临近有效期，我们为其提供了专业人员延续配置、财务与业绩材料整理等全流程指导，按期完成资质延续申报并顺利取证，保障了企业在开发项目的合规推进。</p>"),
    ("某机电工程公司资质增项成功案例",
     "在原有房建资质基础上增项机电工程施工总承包，助力企业拓宽业务范围。",
     "<p>某机电工程有限公司原具备建筑工程施工总承包资质，为承接机电安装项目需增项机电工程施工总承包资质。我们协助企业完成机电专业建造师与中级职称人员配置，编制增项申报材料，顺利通过审核取得增项资质。</p>"),
]

ARTICLE_TEMPLATES = [
    ("2026年建筑业企业资质改革政策要点解读",
     "梳理最新资质改革政策方向，帮助企业提前规划资质配置策略。",
     "<p>资质改革持续深化，施工总承包等级压减、专业承包类别整合是主要方向。企业应结合自身业务范围，提前规划资质配置，避免政策切换期出现资质空档。本文对最新政策要点进行逐条解读，并给出应对建议。</p>"),
    ("资质动态核查高频驳回原因分析与规避指南",
     "总结动态核查中最常见的人员、社保、业绩驳回原因，帮助企业一次通过。",
     "<p>动态核查驳回主要集中在：注册人员数量不达标、社保缴纳单位与注册单位不一致、代表业绩材料缺项等。企业应建立资质维护台账，定期自查人员与社保状态，发现异常及时补救。本文附常见驳回原因对照表与规避措施。</p>"),
    ("建造师注册常见问题解答：初始注册、延续与变更",
     "建造师注册全流程高频问题汇总，涵盖初始注册、延续注册、变更注册与注销。",
     "<p>初始注册需要提供什么材料？延续注册最晚什么时候办理？变更注册单位后原证书如何处理？本文汇总建造师注册全流程高频问题并逐一解答，帮助持证人才与企业快速办理相关手续。</p>"),
    ("安全生产许可证办理条件与延期流程详解",
     "安证办理的三大类人员要求、制度文件清单与延期时间规划。",
     "<p>安全生产许可证与施工资质配套使用，办理需满足三类人员配置、特种作业人员持证、安全制度文件齐全等条件。延期建议提前三个月准备，避免证书过期影响投标。本文详解办理条件、材料清单与延期流程。</p>"),
    ("四库一平台业绩录入规范与常见错误",
     "业绩录入的格式要求、材料附件规范与常见录入错误纠正。",
     "<p>四库一平台的业绩数据直接影响资质申报与升级。录入时需注意项目编号、竣工时间、单体面积等字段与证明材料一致，附件需上传中标通知书、合同、竣工验收证明等关键材料。本文梳理录入规范与高频错误。</p>"),
    ("建筑企业资质维护年度工作清单（收藏版）",
     "人员、社保、证书有效期、安证、动态核查的年度维护清单。",
     "<p>资质维护是持续性工作：注册人员数量保持达标、社保按月足额缴纳、各类证书有效期提前三个月跟进延期、动态核查材料常态化整理。本文提供一份可直接落地的年度维护清单，建议收藏对照执行。</p>"),
]

PRODUCT_TEMPLATES = [
    ("建筑业企业资质新办一站式服务",
     "从人员配置到申报落地的全流程代办，一对一顾问负责制。",
     "<p>为新建建筑企业提供资质新办全流程咨询代办：方案规划、人员招聘配置建议、社保开户、申报材料编制、提交跟进、领证交付。一对一项目顾问负责制，进度节点实时反馈，严控驳回风险。</p>"),
    ("资质升级与增项规划服务",
     "结合企业业绩与人员现状，定制升级/增项路径与实施计划。",
     "<p>根据企业现有资质等级、人员储备与代表业绩情况，评估升级可行性，输出升级/增项路径方案：缺口人员补齐计划、业绩梳理与佐证材料完善、申报窗口期规划，全程跟进至取证。</p>"),
    ("资质动态核查应对与维护服务",
     "年度资质维护托管，人员、社保、材料常态化管理。",
     "<p>提供资质年度维护托管服务：注册人员数量动态监测、社保一致性核对、动态核查材料常态化整理、主管部门核查应对。让企业资质持续有效，随时具备投标条件。</p>"),
    ("建造师注册与人才猎聘服务",
     "一级/二级建造师注册代办与优质人才推荐，配套证书备案咨询。",
     "<p>承接一级/二级建造师初始注册、延续注册、变更注册与注销代办，同时提供建筑行业持证人才猎聘服务：造价工程师、环评工程师等执业证书备案咨询，人才与企业高效匹配。</p>"),
    ("安全生产许可证办理与延期服务",
     "安证新办与延期全流程服务，三类人员配置与制度文件一站式准备。",
     "<p>提供安全生产许可证新办与延期服务：三类人员（A/B/C证）配置与继续教育、特种作业人员持证配置、安全管理制度文件编制、申报提交与审批跟进，保障企业施工合规。</p>"),
    ("资质转让与收购顾问服务",
     "资质公司股权转让尽职调查与交易撮合，风险可控交割清晰。",
     "<p>提供建筑资质公司股权转让的尽职调查服务：债权债务核查、资质有效性核验、历史经营合规性审查，协助双方完成交易谈判与工商变更交割，保障交易安全。</p>"),
]


def load_nanjing_fields() -> dict[str, str]:
    """从 nanjing 库导出各模型 fields JSON（用户配置好的基准）。"""
    db = sqlite3.connect(SITE_ROOT / "nanjing" / "data" / "site.db")
    rows = db.execute("select code, fields from content_type").fetchall()
    db.close()
    return {code: fields for code, fields in rows}


def site_images(site: str) -> list[str]:
    upload = SITE_ROOT / site / "uploads"
    files = sorted(f for f in os.listdir(upload) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    return [f"/uploads/{f}" for f in files]


def main():
    nj_fields = load_nanjing_fields()
    total = {"model_name": 0, "model_fields": 0, "form": 0, "cat_merged": 0, "inserted": 0, "img_fixed": 0}

    for site in ("nanjing", "hefei", "xuzhou", "wuxi", "hangzhou"):
        db = sqlite3.connect(SITE_ROOT / site / "data" / "site.db")

        # 1. content_type 对齐：模型名 + fields 全量覆盖 nanjing 基准
        for code, name in MODEL_NAMES.items():
            row = db.execute("select id, name, fields from content_type where code=?", (code,)).fetchone()
            if not row:
                continue
            cid, cur_name, cur_fields = row
            baseline = nj_fields.get(code)
            if cur_name != name:
                db.execute("update content_type set name=? where id=?", (name, cid))
                total["model_name"] += 1
            if baseline and cur_fields != baseline:
                db.execute("update content_type set fields=? where id=?", (baseline, cid))
                total["model_fields"] += 1

        # 2. form_model 对齐 nanjing 基准
        for code, base in BASE_FORMS.items():
            row = db.execute("select id, name, status, need_login, fields from form_model where code=?", (code,)).fetchone()
            base_json = json.dumps(base["fields"], ensure_ascii=False)
            if not row:
                db.execute(
                    "insert into form_model (name, code, status, need_login, notify_email, fields, created_at, updated_at) "
                    "values (?, ?, ?, ?, '', ?, ?, ?)",
                    (base["name"], code, base["status"], base["need_login"], base_json, NOW, NOW))
                total["form"] += 1
            else:
                fid, name, status, nl, fields = row
                cur = json.loads(fields or "[]")
                if name != base["name"] or json.dumps(cur, ensure_ascii=False, sort_keys=True) != json.dumps(base["fields"], ensure_ascii=False, sort_keys=True):
                    db.execute("update form_model set name=?, status=?, need_login=?, fields=? where id=?",
                               (base["name"], base["status"], base["need_login"], base_json, fid))
                    total["form"] += 1

        # 3. 产品分类只保留一个（主分类），子分类内容迁入主分类后软删
        mains = db.execute(
            "select id from category where model='product' and deleted_at is null and (pid=0 or pid is null)").fetchall()
        if mains:
            main_id = mains[0][0]
            subs = db.execute(
                "select id from category where model='product' and deleted_at is null and pid=? and id!=?",
                (db.execute("select pid from category where id=?", (main_id,)).fetchone()[0] or 0, main_id)).fetchall()
            # 主分类可能本身有 pid（历史数据），直接取该站 pid=0 的 product 主分类
            main_row = db.execute(
                "select id from category where model='product' and deleted_at is null and (pid=0 or pid is null) order by sort limit 1").fetchone()
            main_id = main_row[0]
            subs = db.execute(
                "select id from category where model='product' and deleted_at is null and id!=? and (pid=? or pid in "
                "(select id from category where pid=?))",
                (main_id, main_id, main_id)).fetchall()
            for (sid,) in subs:
                n = db.execute("update content set category_id=? where category_id=? and deleted_at is null",
                               (main_id, sid)).rowcount
                db.execute("update category set deleted_at=?, is_nav=0 where id=?", (NOW, sid))
                total["cat_merged"] += 1

        # 4. 数据量下限：不足则插入模板内容（有图）
        imgs = site_images(site)
        if not imgs:
            # 从 nanjing 复制 10 张图
            src = SITE_ROOT / "nanjing" / "uploads"
            for f in sorted(f for f in os.listdir(src) if f.lower().endswith((".jpg", ".jpeg", ".png")))[:10]:
                shutil.copy(src / f, SITE_ROOT / site / "uploads" / f)
            imgs = site_images(site)

        cats = {"article": None, "product": None, "case": None}
        for m in cats:
            row = db.execute(
                "select id from category where model=? and deleted_at is null and status=1 order by sort limit 1",
                (m,)).fetchone()
            cats[m] = row[0] if row else None

        templates = {"case": CASE_TEMPLATES, "article": ARTICLE_TEMPLATES, "product": PRODUCT_TEMPLATES}
        for m, min_n in MIN_COUNTS.items():
            cur_n = db.execute("select count(*) from content where model=? and deleted_at is null", (m,)).fetchone()[0]
            if cur_n >= min_n or not cats[m]:
                continue
            for i, (title, summary, body) in enumerate(templates[m]):
                if cur_n + i >= min_n:
                    break
                t = f"{title}" if site == "nanjing" else title
                db.execute(
                    "insert into content (model, category_id, title, summary, body, cover, status, is_top, is_hot, "
                    "view_count, sort, created_at, updated_at) values (?, ?, ?, ?, ?, ?, 'publish', 0, 0, 0, 0, ?, ?)",
                    (m, cats[m], t, summary, body, imgs[(cur_n + i + 1) % len(imgs)], NOW, NOW))
                total["inserted"] += 1

        # 5. 所有 article/product/case/page 必须有图
        rows = db.execute(
            "select id, model from content where deleted_at is null and (cover is null or cover='') "
            "and model in ('article','product','case','page')").fetchall()
        for cid, model in rows:
            offset = {"article": 0, "product": 1, "case": 2, "page": 3}.get(model, 0)
            db.execute("update content set cover=? where id=?", (imgs[(cid * (offset + 1) + offset) % len(imgs)], cid))
            total["img_fixed"] += 1

        db.commit()
        counts = db.execute(
            "select model, count(*), sum(case when cover is null or cover='' then 1 else 0 end) "
            "from content where deleted_at is null and model in ('article','product','case') group by model").fetchall()
        pcats = db.execute("select count(*) from category where model='product' and deleted_at is null").fetchone()[0]
        print(f"{site}: 模型={dict((m, f'{n}条/缺图{e}') for m, n, e in counts)} | product分类={pcats}")
        db.close()

    print(f"\n汇总: 模型改名 {total['model_name']} | fields覆盖 {total['model_fields']} | 表单对齐 {total['form']} | "
          f"分类合并 {total['cat_merged']} | 补内容 {total['inserted']} | 补图 {total['img_fixed']}")


if __name__ == "__main__":
    main()
