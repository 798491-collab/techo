"""生成五个站点的种子数据 seed.json（基于真实公司资料）。"""
from __future__ import annotations

import json
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[2]   # 项目根目录（本文件在 <site>/scripts/ 下）


def slugify(name: str) -> str:
    slugs = {
        "关于我们": "about", "走进玖硕": "about", "关于筑骋": "about", "关于君鑫": "about", "关于志俞": "about",
        "服务项目": "service", "资质服务": "service", "服务领域": "service", "咨询服务": "service", "人才服务": "talent",
        "精选案例": "case", "工程案例": "case", "成功案例": "case", "案例展示": "case",
        "新闻资讯": "news", "资讯中心": "news", "行业动态": "news", "新闻中心": "news", "公司动态": "news",
        "联系我们": "contact", "联系玖硕": "contact",
    }
    return slugs.get(name, name)


def make_categories(nav: list[dict]) -> list[dict]:
    cats = []
    for i, n in enumerate(nav):
        slug = n["slug"] or "home"
        if slug == "home":
            continue
        model = "page" if slug in ("about", "contact") else ("case" if slug in ("case", "anli") else "article")
        if slug in ("zizhi", "rencai", "service", "talent"):
            model = "product"
        cats.append({
            "name": n["name"], "slug": slug, "model": model, "pid": 0,
            "is_nav": 1, "sort": i, "status": 1,
            "description": f"{n['name']} - 专业服务与资讯",
            "seo_title": n["name"], "seo_keywords": "", "seo_description": "",
        })
    return cats


# 所有站点内置表单模型：在线留言（需求：URL ?guest_book 填写并 ajax 提交）
GUEST_BOOK_FORM = {
    "name": "在线留言", "code": "guest_book", "need_login": 0,
    "notify_email": "", "status": 1,
    "fields": [
        {"label": "姓名", "field": "name", "type": "text", "required": 1, "default": "", "options": []},
        {"label": "手机号码", "field": "phone", "type": "text", "required": 1, "default": "", "options": []},
        {"label": "公司", "field": "company", "type": "text", "required": 0, "default": "", "options": []},
        {"label": "内容", "field": "content", "type": "textarea", "required": 0, "default": "", "options": []},
        {"label": "需要回复", "field": "need_reply", "type": "radio", "required": 0, "default": "否",
         "options": [{"label": "是", "value": "是"}, {"label": "否", "value": "否"}]},
    ],
}


def C(cat_slug, title, summary, body, **kw):
    d = {
        "category_slug": cat_slug, "model": kw.pop("model", "article"),
        "title": title, "subtitle": kw.pop("subtitle", ""), "summary": summary,
        "body": body, "author": kw.pop("author", ""), "source": kw.pop("source", "原创"),
        "tags": kw.pop("tags", ""), "status": "publish", "publish_at": "now",
        "is_top": kw.pop("is_top", 0), "is_hot": kw.pop("is_hot", 0),
        "seo_title": title, "seo_keywords": kw.pop("seo_keywords", ""), "seo_description": summary[:150],
        "sort": kw.pop("sort", 0), "cover": kw.pop("cover", ""),
    }
    d.update(kw)
    return d


def nav_images(site_key: str, limit: int):
    upload = SITE_ROOT / site_key / "uploads"
    files = sorted([p.name for p in upload.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')])
    return [f"/uploads/{n}" for n in files[:limit]]


def nanjing():
    imgs = nav_images("nanjing", 2)
    cats = make_categories(json.loads((SITE_ROOT/"nanjing"/"site.json").read_text(encoding="utf-8")).get("nav") or [])
    return {
      "admin": {"username": "admin", "password": "${PYSITE_ADMIN_PASSWORD}", "nickname": "南京站管理员"},
      "settings": {
        "site_name": "南京筑韬建筑工程有限公司", "site_phone": "025-8501 6688",
        "site_mobile": "17710727587", "site_email": "service@nj-zhutao.com",
        "site_address": "江苏省南京市",
        "site_keywords": "南京建筑资质代办,建筑资质新办,建造师注册",
        "site_description": "南京筑韬建筑工程有限公司，专注建筑企业资质与建工人才注册一站式咨询服务。",
        "site_copyright": "© 2026 南京筑韬建筑工程有限公司 版权所有",
        "site_wechat": "/uploads/微信二维码.jpg" if (SITE_ROOT/"nanjing"/"uploads"/"微信二维码.jpg").exists() else "",
      },
      "tags": [{"name": "建筑资质", "sort": 1}, {"name": "建造师", "sort": 2}, {"name": "资质新办", "sort": 3}, {"name": "人才注册", "sort": 4}],
      "categories": cats,
      "forms": [GUEST_BOOK_FORM, {"name": "在线咨询", "code": "consult", "fields": [
        {"label": "姓名", "name": "name", "type": "text", "required": True},
        {"label": "电话", "name": "phone", "type": "text", "required": True},
        {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
      ], "notify_email": "", "status": 1}],
      "contents": [
        C("about", "关于筑韬", "南京筑韬建筑工程有限公司，是专注建筑行业一站式咨询服务机构，深耕建筑企业资质与建工人才注册两大业务板块。",
          """<h2>关于筑韬</h2><p>南京筑韬建筑工程有限公司，是专注建筑行业一站式咨询服务机构，深耕建筑企业资质与建工人才注册两大业务板块。</p><p>团队熟悉住建审批政策、四库一平台申报规则，专业为建筑企业提供建筑业资质新办、动态核查维护；同时承接一级/二级建造师注册、注销全流程咨询代办，配套造价工程师、环评工程师等执业证书备案咨询服务。</p><p>从前期方案规划、申报提交，到审核跟进、办结交付，实行一对一项目顾问负责制。坚持合规申报、流程透明，严控申报驳回风险，助力企业快速取得资质、完成人员注册，降低企业资质维护成本。</p><p>服务覆盖房建、公路等多专业建筑企业，兼顾持证人才注册咨询。守信为宗旨，为建筑企业资质全周期管理与建工执业人才注册提供稳定可靠的解决方案。</p>""",
          model="page", is_top=1),
        C("zizhi", "建筑业企业资质新办与升级", "熟悉住建审批政策与四库一平台申报规则，为建筑企业提供资质新办、增项、升级与变更服务。",
          """<h2>建筑业企业资质服务</h2><p>我们为建筑企业提供建筑业施工资质新办、增项、升级、变更、延期等全流程咨询代办服务。</p><ul><li>建筑业企业资质新办、增项、升级</li><li>资质动态核查与维护</li><li>安全生产许可证办理咨询</li><li>四库一平台信息申报与维护</li></ul><p>一对一项目顾问负责制，从方案规划到办结交付全程跟进，严控申报驳回风险。</p>""",
          model="product", is_hot=1, tags="建筑资质,资质新办"),
        C("zizhi", "资质动态核查与维护", "帮助企业应对资质动态核查，建立健全资质维护机制，降低资质维护成本。",
          """<h2>资质动态核查与维护</h2><p>针对住建部门资质动态核查要求，我们为企业提供人员配置核查、社保比对、业绩材料整理等一站式维护服务，确保企业资质持续有效。</p>""", model="product", tags="建筑资质"),
        C("rencai", "一级/二级建造师注册代办", "承接一级、二级建造师注册、注销全流程咨询代办，配套造价工程师、环评工程师等执业证书备案咨询。",
          """<h2>建工人才注册服务</h2><p>我们承接一级/二级建造师注册、注销、变更全流程咨询代办服务，同时提供造价工程师、环评工程师等执业证书备案咨询。</p><ul><li>一级/二级建造师注册与注销</li><li>造价工程师、环评工程师证书备案</li><li>持证人才注册咨询</li><li>人员配置方案规划</li></ul>""", model="product", is_hot=1, tags="建造师,人才注册"),
        C("news", "建筑企业资质动态核查常见问题解析", "梳理建筑企业资质动态核查中的常见问题，帮助企业提前准备、合规应对。",
          """<h2>资质动态核查常见问题解析</h2><p>资质动态核查主要关注企业人员、社保、业绩等方面。我们梳理了常见问题，帮助企业提前准备、合规应对，避免因材料不齐或人员不符导致核查不通过。</p>""", tags="建筑资质"),
        C("news", "四库一平台申报要点与注意事项", "全国建筑市场监管公共服务平台信息申报要点解读。",
          """<h2>四库一平台申报要点</h2><p>四库一平台是建筑市场监管的重要数据基础。企业信息的准确性、完整性直接影响资质申报与核查结果。本文梳理申报过程中的关键要点与常见错误。</p>""", tags="建筑资质"),
        C("news", "建造师注册流程与材料清单", "一级、二级建造师注册全流程解析与材料准备清单。",
          """<h2>建造师注册流程详解</h2><p>建造师注册涉及申请、审核、公示等多个环节。我们整理了完整的流程说明与材料清单，帮助企业和持证人才高效完成注册。</p>""", tags="建造师"),
        C("contact", "联系我们", "欢迎来电或到访咨询，我们将竭诚为您服务。",
          """<h2>联系我们</h2><p>南京筑韬建筑工程有限公司，期待与您合作。</p><p><strong>电话：</strong>025-8501 6688</p><p><strong>手机：</strong>17710727587</p><p><strong>邮箱：</strong>service@nj-zhutao.com</p><p><strong>地址：</strong>江苏省南京市</p>""", model="page"),
      ],
    }


def hefei():
    imgs = nav_images("hefei", 8)
    cats = make_categories(json.loads((SITE_ROOT/"hefei"/"site.json").read_text(encoding="utf-8")).get("nav") or [])
    cases = []
    for i in range(6):
        cases.append(C("case", f"工程造价咨询服务案例 {i+1}", "为建筑企业提供专业、高效的工程造价咨询服务，助力项目成本控制与投资效益提升。",
          f"<h2>服务案例 {i+1}</h2><p>我们为建筑企业提供工程造价咨询、工程管理服务，涵盖预算编制、结算审核、全过程造价控制等内容。以专业筑根基，以诚信赢信赖。</p>",
          model="case", cover=imgs[i % len(imgs)] if imgs else "", tags="工程造价"))
    return {
      "admin": {"username": "admin", "password": "${PYSITE_ADMIN_PASSWORD}", "nickname": "合肥站管理员"},
      "settings": {
        "site_name": "合肥筑骋建筑工程咨询有限公司", "site_phone": "13083005831",
        "site_mobile": "15062190605", "site_email": "service@hf-zhucheng.com",
        "site_address": "合肥市蜀山区华地金融中心",
        "site_keywords": "合肥工程造价咨询,工程管理,商务代理代办,项目策划",
        "site_description": "合肥筑骋建筑工程咨询有限公司，专注建筑工程咨询服务，为客户提供工程管理、造价咨询、商务代理代办与项目策划等配套服务。",
        "site_copyright": "© 2026 合肥筑骋建筑工程咨询有限公司 版权所有",
      },
      "tags": [{"name": "工程造价", "sort": 1}, {"name": "工程管理", "sort": 2}, {"name": "项目策划", "sort": 3}, {"name": "商务代办", "sort": 4}],
      "categories": cats,
      "forms": [GUEST_BOOK_FORM, {"name": "在线咨询", "code": "consult", "fields": [
        {"label": "姓名", "name": "name", "type": "text", "required": True},
        {"label": "电话", "name": "phone", "type": "text", "required": True},
        {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
      ], "notify_email": "", "status": 1}],
      "contents": [
        C("about", "关于筑骋", "合肥筑骋建筑工程咨询有限公司，专注建筑工程咨询服务，以专业筑根基，以诚信赢信赖。",
          """<h2>关于筑骋</h2><p>以专业筑根基，以诚信赢信赖。</p><p>合肥筑骋建筑工程咨询有限公司，专注建筑工程咨询服务，为客户提供工程管理、造价咨询、商务代理代办与项目策划等配套服务。深耕行业，用心做好每一次服务。</p><p><strong>办公地址：</strong>合肥蜀山区华地金融中心</p><p><strong>联系电话：</strong>13083005831 / 15062190605</p>""",
          model="page", is_top=1),
        C("service", "工程造价咨询", "提供投资估算、设计概算、施工图预算、工程结算、竣工决算等全过程造价咨询服务。",
          """<h2>工程造价咨询</h2><p>我们提供投资估算、设计概算、施工图预算、工程结算、竣工决算等全过程造价咨询服务，为项目决策与成本控制提供专业依据。</p>""",
          model="product", is_hot=1, tags="工程造价"),
        C("service", "工程管理服务", "覆盖项目全周期的工程管理服务，保障工程质量、进度与投资控制。",
          """<h2>工程管理服务</h2><p>覆盖项目前期策划、设计管理、招投标管理、施工管理等全周期工程管理服务，保障工程质量、进度与投资控制。</p>""", model="product", tags="工程管理"),
        C("service", "商务代理代办", "提供企业设立、商务代理、资质代办等配套服务", """<h2>商务代理代办</h2><p>为企业提供工商注册、商务代理、资质代办等一站式配套服务，让企业专注于核心业务。</p>""", model="product", tags="商务代办"),
        C("service", "项目策划与咨询", "提供项目可行性研究、投资分析与策划咨询服务。", """<h2>项目策划咨询</h2><p>提供项目可行性研究、投资分析、市场研究与策划咨询服务，助力企业科学决策。</p>""", model="product", tags="项目策划"),
        C("news", "工程造价咨询在项目管理中的价值", "解析工程造价咨询如何帮助建筑企业实现成本精细化管理。",
          """<h2>工程造价咨询的价值</h2><p>工程造价咨询贯穿项目全生命周期，通过科学的成本估算、预算控制与结算审核，帮助建筑企业实现成本精细化管理，提升投资效益。</p>""", tags="工程造价"),
        C("news", "建筑企业如何做好项目前期策划", "分享建筑企业项目前期策划的关键要素与实践方法。",
          """<h2>项目前期策划要点</h2><p>项目前期策划决定了项目的方向与成败。本文分享市场研究、投资估算、风险评估等关键要素。</p>""", tags="项目策划"),
        C("contact", "联系我们", "欢迎来电或到访咨询。",
          """<h2>联系我们</h2><p><strong>地址：</strong>合肥市蜀山区华地金融中心</p><p><strong>电话：</strong>13083005831</p><p><strong>手机：</strong>15062190605</p>""", model="page"),
      ] + cases,
    }


def xuzhou():
    imgs = nav_images("xuzhou", 8)
    cats = make_categories(json.loads((SITE_ROOT/"xuzhou"/"site.json").read_text(encoding="utf-8")).get("nav") or [])
    cases = []
    for i in range(5):
        cases.append(C("case", f"建筑工程咨询服务案例 {i+1}", "立足徐州本地，为建筑行业企业提供专业、高效的工程咨询服务。",
          f"<h2>服务案例 {i+1}</h2><p>我们立足徐州本地，面向建筑行业市场，为客户提供建筑工程相关技术咨询、施工资质代办与维护、注册人员配备等服务。</p>",
          model="case", cover=imgs[i % len(imgs)] if imgs else "", tags="工程咨询"))
    return {
      "admin": {"username": "admin", "password": "${PYSITE_ADMIN_PASSWORD}", "nickname": "徐州站管理员"},
      "settings": {
        "site_name": "徐州玖硕建筑工程咨询有限公司", "site_phone": "0516-8388 6688", "site_mobile": "",
        "site_email": "service@xz-jiushuo.com", "site_address": "江苏省徐州市云龙区黄山路",
        "site_keywords": "徐州建筑资质代办,施工资质维护,注册人员配备",
        "site_description": "徐州玖硕建筑工程咨询有限公司成立于2025年5月，专注建筑工程领域专业咨询服务。",
        "site_copyright": "© 2026 徐州玖硕建筑工程咨询有限公司 版权所有",
      },
      "tags": [{"name": "施工资质", "sort": 1}, {"name": "技术咨询", "sort": 2}, {"name": "人员配备", "sort": 3}],
      "categories": cats,
      "forms": [GUEST_BOOK_FORM, {"name": "在线咨询", "code": "consult", "fields": [
        {"label": "姓名", "name": "name", "type": "text", "required": True},
        {"label": "电话", "name": "phone", "type": "text", "required": True},
        {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
      ], "notify_email": "", "status": 1}],
      "contents": [
        C("about", "走进玖硕", "徐州玖硕建筑工程咨询有限公司成立于2025年5月9日，专注建筑工程领域专业咨询服务。",
          """<h2>走进玖硕</h2><p>徐州玖硕建筑工程咨询有限公司成立于2025年05月09日，注册地位于江苏省徐州市云龙区黄山路，公司专注于建筑工程领域专业咨询服务。</p><p>立足徐州本地，面向建筑行业市场，可为客户提供建筑工程相关技术咨询、施工资质代办与维护、注册人员配备。</p><p>公司秉持严谨务实的服务理念，依托本地化优势，聚焦工程咨询业务，致力于为合作方提供可靠、高效的工程咨询解决方案。</p>""",
          model="page", is_top=1),
        C("service", "建筑工程施工资质代办与维护", "提供施工资质新办、增项、升级、变更与日常维护服务。",
          """<h2>施工资质代办与维护</h2><p>我们为建筑企业提供施工资质新办、增项、升级、变更、延续等全流程代办服务，以及资质日常维护、动态核查应对等配套服务。</p>""", model="product", is_hot=1, tags="施工资质"),
        C("service", "建筑工程技术咨询", "提供建筑工程领域专业咨询服务，解答企业技术难题。",
          """<h2>建筑工程技术咨询</h2><p>依托专业团队，为建筑企业提供项目技术咨询、技术方案论证、规范解读等专业咨询服务。</p>""", model="product", tags="技术咨询"),
        C("service", "注册人员配备", "为建筑企业提供注册人员配备与证书咨询服务。",
          """<h2>注册人员配备</h2><p>为建筑企业提供建造师、工程师等注册人员配备咨询，助力企业满足资质标准要求。</p>""", model="product", tags="人员配备"),
        C("news", "建筑施工资质维护的注意事项", "分享施工资质日常维护的关键要点，帮助企业避免资质风险。",
          """<h2>资质维护要点</h2><p>施工资质需要企业持续满足人员、业绩等标准要求。本文梳理日常维护中的关键事项。</p>""", tags="施工资质"),
        C("news", "建筑行业咨询服务的价值与趋势", "分析建筑行业咨询服务的发展现状与未来趋势。",
          """<h2>行业趋势分析</h2><p>随着建筑行业规范化发展，专业咨询服务的重要性日益凸显。本文分析行业发展趋势。</p>""", tags="工程咨询"),
        C("contact", "联系玖硕", "欢迎来电咨询，我们立足徐州，服务建筑行业。",
          """<h2>联系玖硕</h2><p><strong>地址：</strong>江苏省徐州市云龙区黄山路</p><p><strong>电话：</strong>0516-8388 6688</p><p><strong>邮箱：</strong>service@xz-jiushuo.com</p>""", model="page"),
      ] + cases,
    }


def wuxi():
    cats = make_categories(json.loads((SITE_ROOT/"wuxi"/"site.json").read_text(encoding="utf-8")).get("nav") or [])
    return {
      "admin": {"username": "admin", "password": "${PYSITE_ADMIN_PASSWORD}", "nickname": "无锡站管理员"},
      "settings": {
        "site_name": "无锡君鑫建筑工程咨询有限公司", "site_phone": "17710727587", "site_mobile": "17710727587",
        "site_email": "service@wx-junxin.com", "site_address": "江苏省无锡市梁溪区清扬路118号世金中心2804",
        "site_keywords": "无锡建筑资质咨询,造价咨询,安许办理",
        "site_description": "无锡君鑫建筑工程咨询有限公司，专注建筑行业一站式工程咨询服务。",
        "site_copyright": "© 2026 无锡君鑫建筑工程咨询有限公司 版权所有",
      },
      "tags": [{"name": "建筑资质", "sort": 1}, {"name": "造价咨询", "sort": 2}, {"name": "安许办理", "sort": 3}, {"name": "人才证书", "sort": 4}],
      "categories": cats,
      "forms": [GUEST_BOOK_FORM, {"name": "在线咨询", "code": "consult", "fields": [
        {"label": "姓名", "name": "name", "type": "text", "required": True},
        {"label": "电话", "name": "phone", "type": "text", "required": True},
        {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
      ], "notify_email": "", "status": 1}],
      "contents": [
        C("about", "关于君鑫", "无锡君鑫建筑工程咨询有限公司坐落于无锡市梁溪区，专注建筑行业一站式工程咨询服务。",
          """<h2>关于君鑫</h2><p>无锡君鑫建筑工程咨询有限公司坐落于无锡市梁溪区，是专注于建筑行业一站式工程咨询服务企业，现有员工50人，汇聚工程管理、造价、建筑技术、资质服务等专业人才，团队实战经验丰富，服务覆盖江苏及全国多地建筑市场。</p><p>公司深耕建筑工程咨询领域，围绕建筑企业发展需求，提供建筑资质咨询、工程项目技术咨询、造价咨询、工程资料辅导、人才证书配套咨询、安许办理咨询等专业服务，业务涵盖房建、市政、装饰、路桥等多个工程类别。</p><p>自成立以来，公司坚守"君承诚信，鑫筑共赢"的经营理念，以专业、高效、合规为服务准则，建立标准化服务流程，重视风险把控，为建筑企业解决资质申报、人员配置、项目咨询等各类难题。</p><p><strong>地址：</strong>江苏省无锡市梁溪区清扬路118号世金中心2804<br><strong>联系人：</strong>杜总 17710727587</p>""",
          model="page", is_top=1),
        C("service", "建筑资质咨询服务", "提供建筑资质申报、升级、变更与维护全流程咨询。",
          """<h2>建筑资质咨询</h2><p>为建筑企业提供资质申报、升级、变更、延续等全流程咨询服务，熟悉审批政策与申报要求，助力企业合规高效地取得与维护资质。</p>""", model="product", is_hot=1, tags="建筑资质"),
        C("service", "工程造价咨询服务", "提供预算编制、结算审核、全过程造价控制等专业服务。",
          """<h2>工程造价咨询</h2><p>拥有专业造价团队，提供投资估算、预算编制、结算审核、全过程造价控制等服务，覆盖房建、市政、装饰、路桥等多个工程类别。</p>""", model="product", tags="造价咨询"),
        C("service", "工程项目技术咨询", "为建筑企业提供项目技术分析与方案论证服务。",
          """<h2>工程项目技术咨询</h2><p>依托资深技术团队，为工程项目提供技术咨询、方案论证、规范解读等服务，助力项目顺利推进。</p>""", model="product", tags="技术咨询"),
        C("service", "安许办理与人才证书配套", "安全生产许可证办理咨询与人才证书备案配套服务。",
          """<h2>安许办理与人才证书</h2><p>提供安全生产许可证办理咨询、人才证书配套咨询、工程资料辅导等服务，为企业解决人员配置与证书办理难题。</p>""", model="product", tags="安许办理,人才证书"),
        C("news", "建筑企业资质申报的流程与要点", "梳理建筑企业资质申报的关键流程与注意事项。",
          """<h2>资质申报要点</h2><p>资质申报涉及材料准备、人员配置、审批流程等多个环节。我们梳理关键流程与注意事项，帮助企业少走弯路。</p>""", tags="建筑资质"),
        C("news", "工程造价控制的常见误区", "分析工程造价控制中常见的问题与应对策略。",
          """<h2>造价控制误区</h2><p>工程造价控制贯穿项目全过程，本文分析常见误区并提供应对策略。</p>""", tags="造价咨询"),
        C("case", "房建工程咨询服务案例", "为房建工程企业提供资质、造价、技术一站式咨询服务。",
          """<h2>房建工程服务案例</h2><p>我们为多家房建工程企业提供资质咨询、造价咨询与技术支持，助力企业高效推进项目。</p>""", model="case", tags="房建"),
        C("contact", "联系我们", "欢迎来电咨询，君承诚信，鑫筑共赢。",
          """<h2>联系我们</h2><p><strong>地址：</strong>江苏省无锡市梁溪区清扬路118号世金中心2804</p><p><strong>联系人：</strong>杜总 17710727587</p><p><strong>邮箱：</strong>service@wx-junxin.com</p>""", model="page"),
      ],
    }


def hangzhou():
    imgs = nav_images("hangzhou", 8)
    cats = make_categories(json.loads((SITE_ROOT/"hangzhou"/"site.json").read_text(encoding="utf-8")).get("nav") or [])
    news = []
    for i in range(3):
        news.append(C("case", f"建筑资质办理服务案例 {i+1}", "志俞建筑专注建筑资质办理与建工人才服务，助力企业稳健发展。",
          f"<h2>服务案例 {i+1}</h2><p>我们专注建筑资质办理与建工人才服务，为企业和人才提供专业、高效的一站式咨询服务。</p>",
          model="case", cover=imgs[i % len(imgs)] if imgs else "", tags="服务案例"))
    for i in range(5):
        news.append(C("news", f"公司动态 {i+1}：专业服务，携手共进", "志俞建筑专注建筑资质办理与建工人才服务，助力企业稳健发展。",
          f"<h2>公司动态</h2><p>杭州志俞建筑工程咨询有限公司专注建筑资质办理与建工人才服务，为企业和人才提供专业、高效的一站式咨询服务。我们坚持以诚信为本，携手共进，筑梦未来。</p>",
          cover=imgs[i % len(imgs)] if imgs else "", tags="公司动态"))
    return {
      "admin": {"username": "admin", "password": "${PYSITE_ADMIN_PASSWORD}", "nickname": "杭州站管理员"},
      "settings": {
        "site_name": "杭州志俞建筑工程咨询有限公司", "site_phone": "0571-8698 6688", "site_mobile": "",
        "site_email": "service@hz-zhiyu.com", "site_address": "浙江省杭州市",
        "site_keywords": "杭州建筑资质代办,建筑人才服务,资质证书办理",
        "site_description": "杭州志俞建筑工程咨询有限公司，专注建筑资质办理与建工人才服务。",
        "site_copyright": "© 2026 杭州志俞建筑工程咨询有限公司 版权所有",
      },
      "tags": [{"name": "建筑资质", "sort": 1}, {"name": "人才服务", "sort": 2}, {"name": "证书办理", "sort": 3}],
      "categories": cats,
      "forms": [GUEST_BOOK_FORM, {"name": "在线咨询", "code": "consult", "fields": [
        {"label": "姓名", "name": "name", "type": "text", "required": True},
        {"label": "电话", "name": "phone", "type": "text", "required": True},
        {"label": "咨询内容", "name": "content", "type": "textarea", "required": True},
      ], "notify_email": "", "status": 1}],
      "contents": [
        C("about", "关于志俞", "杭州志俞建筑工程咨询有限公司，专注建筑资质办理与建工人才服务。",
          """<h2>关于志俞</h2><p>杭州志俞建筑工程咨询有限公司，专注建筑资质办理与建工人才服务，为企业和人才提供专业、高效的一站式咨询服务。</p><p>我们秉持"志存高远、俞信于行"的理念，以诚信为本，专业为基，助力建筑企业稳健发展，搭建企业与人才的双赢桥梁。</p>""",
          model="page", is_top=1),
        C("service", "建筑资质办理服务", "提供建筑施工资质新办、升级、变更、延期等全流程服务。",
          """<h2>建筑资质办理</h2><p>我们为建筑企业提供施工资质新办、增项、升级、变更、延期等全流程办理服务，熟悉审批政策，助力企业高效取得资质。</p>""", model="product", is_hot=1, tags="建筑资质"),
        C("service", "资质证书咨询服务", "提供各类建筑资质证书的咨询与办理指导。",
          """<h2>资质证书咨询</h2><p>提供各类建筑资质证书、安全生产许可证的咨询与办理指导服务。</p>""", model="product", tags="证书办理"),
        C("talent", "建工人才服务", "为建筑企业与持证人才搭建对接桥梁，提供注册、备案等配套服务。",
          """<h2>建工人才服务</h2><p>我们为建筑企业与持证人才搭建高效对接桥梁，提供建造师、工程师等人才注册、备案等配套服务，助力企业满足资质人才要求，帮助人才实现职业价值。</p>""", model="product", is_hot=1, tags="人才服务"),
        C("news", "建筑资质办理的常见流程解析", "梳理建筑资质办理的完整流程与注意事项。",
          """<h2>资质办理流程</h2><p>建筑资质办理涉及材料准备、人员配置、申报审批等多个环节。本文梳理完整流程与注意事项。</p>""", tags="建筑资质"),
        C("news", "建工人才注册的趋势与机遇", "分析建工人才注册领域的发展现状与机遇。",
          """<h2>人才服务趋势</h2><p>随着建筑行业规范化发展，持证人才的需求持续增长。本文分析建工人才注册领域的发展趋势。</p>""", tags="人才服务"),
        C("contact", "联系我们", "欢迎来电咨询，志存高远，俞信于行。",
          """<h2>联系我们</h2><p><strong>地址：</strong>浙江省杭州市</p><p><strong>电话：</strong>0571-8698 6688</p><p><strong>邮箱：</strong>service@hz-zhiyu.com</p>""", model="page"),
      ] + news,
    }


GENERATORS = {"nanjing": nanjing, "hefei": hefei, "xuzhou": xuzhou, "wuxi": wuxi, "hangzhou": hangzhou}

if __name__ == "__main__":
    for key, gen in GENERATORS.items():
        data = gen()
        path = SITE_ROOT / key / "storage" / "seed.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{key}: {len(data['categories'])} 栏目, {len(data['contents'])} 内容")
