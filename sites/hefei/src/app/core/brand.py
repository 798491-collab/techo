"""品牌配置文件（单一来源）：站点名称 / Slogan / 版本号 / 登录页文案。

修改本文件即可全局更新后台侧栏、登录页、页面标题等处的品牌信息，
无需改动任何模板。运行时也可被 Setting 表中的同名 key 覆盖（site_name 优先）。
"""
from __future__ import annotations

BRAND = {
    # 侧栏与页面标题
    "name": "企业管理系统",
    "logo": "bi-layers-half",           # Bootstrap Icons 图标类名
    "slogan": "AI 轻量化管理后台",       # 侧栏名称下方副标题
    "version": "V35.26.1351",

    # 登录页
    "login_title": "AI 轻量化管理后台",
    "login_desc": (
        "现代化管理平台，支持本地、私有、云端多种方式灵活部署。"
        "采用多站独立架构，严格实现站点数据隔离；内置多款主题，支持一键切换，快速更换界面风格。"
        "插件化扩展能力，搭配细粒度权限体系，访问权限可控，全方位保障业务安全稳定。"
        "适用于站点运维、资源统一管控、SaaS 多实例运营等场景，"
        "提供社区版与商业版双重授权方案。"
    ),
    "login_site": "www.cms-system.cn",   # 登录页底部站点标识
}


def brand_public() -> dict:
    """返回可公开下发到前端的品牌信息（不含敏感内容）。"""
    return {
        "name": BRAND["name"],
        "logo": BRAND["logo"],
        "slogan": BRAND["slogan"],
        "version": BRAND["version"],
        "login_title": BRAND["login_title"],
        "login_desc": BRAND["login_desc"],
        "login_site": BRAND["login_site"],
    }
