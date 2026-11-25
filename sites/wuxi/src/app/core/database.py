"""全站共用数据模型（每个站点一份独立 SQLite，表结构完全相同）。

严格按《站群CMS需求规格说明书 V3.1》第 7 章「全量数据模型」建表：
系统后台、站群、多语言、内容、会员、表单、订单库存、评论，共 40+ 张表。

保留早期简化字段名（兼容已有 seed.json），并补齐文档要求的全部字段。
软删除表统一带 deleted_at / deleted_by 字段。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, Numeric, String, Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class TimestampMixin:
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class SoftDeleteMixin:
    deleted_at = Column(DateTime, nullable=True, default=None)
    deleted_by = Column(Integer, nullable=True, default=None)


# ==================== 7.1 系统后台模型（无软删除） ====================
class AdminUser(Base, TimestampMixin):
    """管理员"""
    __tablename__ = "admin_user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(64), default="")
    avatar = Column(String(255), default="")
    role = Column(String(32), default="admin")        # super / admin / editor
    status = Column(Integer, default=1)
    is_super = Column(Integer, default=0)
    mobile = Column(String(32), default="")
    email = Column(String(128), default="")
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(64), default="")
    prev_login_at = Column(DateTime, nullable=True)                     # 上次登录时间（本次登录前的记录）
    prev_login_ip = Column(String(64), default="")
    remark = Column(String(500), default="")


class AdminRole(Base, TimestampMixin):
    """角色"""
    __tablename__ = "admin_role"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    rules = Column(Text, default="[]")               # list[str] 功能权限 key
    site_ids = Column(Text, default="[]")             # list[int] 可管理站点，空=全部
    status = Column(Integer, default=1)


class AdminPermission(Base, TimestampMixin):
    """权限节点（树形）"""
    __tablename__ = "admin_permission"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), default="")
    key = Column(String(128), default="", index=True)
    pid = Column(Integer, default=0)
    type = Column(String(16), default="menu")         # menu / button / api
    path = Column(String(128), default="")
    icon = Column(String(64), default="")
    sort = Column(Integer, default=0)
    status = Column(Integer, default=1)


class OperationLog(Base, TimestampMixin):
    """操作审计"""
    __tablename__ = "operation_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user = Column(String(64), default="")
    admin_user_id = Column(Integer, default=0)
    site_id = Column(Integer, default=0)
    module = Column(String(64), default="")
    action = Column(String(32), default="")
    target = Column(String(255), default="")
    detail = Column(Text, default="")
    url = Column(String(500), default="")
    ip = Column(String(64), default="")
    user_agent = Column(String(500), default="")


class AdminConfig(Base, TimestampMixin):
    """全局配置（key-value）"""
    __tablename__ = "admin_config"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, default="")
    group = Column(String(64), default="basic")
    remark = Column(String(255), default="")


class Media(Base, TimestampMixin):
    """素材 admin_upload_file"""
    __tablename__ = "media"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    admin_user_id = Column(Integer, default=0)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    storage_path = Column(String(512), default="")
    file_type = Column(String(16), default="image")    # image / video / file
    file_ext = Column(String(16), default="")
    ext = Column(String(16), default="")
    size = Column(Integer, default=0)
    mime = Column(String(128), default="")
    mime_type = Column(String(128), default="")
    md5 = Column(String(64), default="", index=True)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    used_count = Column(Integer, default=0)
    folder = Column(String(128), default="")


class AdminTask(Base, TimestampMixin):
    """定时任务"""
    __tablename__ = "admin_task"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="")
    task_key = Column(String(128), default="", index=True)
    cron = Column(String(64), default="0 2 * * *")
    params = Column(Text, default="{}")
    status = Column(Integer, default=1)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)


class AdminTaskLog(Base, TimestampMixin):
    """任务日志"""
    __tablename__ = "admin_task_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, default=0, index=True)
    status = Column(String(16), default="success")     # success / fail
    result = Column(Text, default="")
    run_at = Column(DateTime, nullable=True)


class AdminBackup(Base, TimestampMixin):
    """备份记录"""
    __tablename__ = "admin_backup"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    filename = Column(String(255), default="")
    storage_path = Column(String(512), default="")
    size = Column(Integer, default=0)
    status = Column(String(16), default="success")


class ApiConsumer(Base, TimestampMixin):
    """开放接口消费方（AppKey/AppSecret 鉴权）"""
    __tablename__ = "api_consumer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(128), default="")                  # 消费方名称
    app_key = Column(String(64), default="", index=True)    # 公开标识
    app_secret = Column(String(128), default="")            # 私有密钥
    total_calls = Column(Integer, default=0)                # 总调用次数
    today_calls = Column(Integer, default=0)                # 今日调用次数
    today_date = Column(String(10), default="")             # 今日计数归属日期 YYYY-MM-DD
    status = Column(Integer, default=1)                     # 1 启用 / 0 禁用
    remark = Column(String(255), default="")


# ==================== 7.2 站群模型 ====================
class Region(Base, TimestampMixin):
    """地区库（全国行政区划）"""
    __tablename__ = "region"
    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, default=0, index=True)
    code = Column(String(32), default="", index=True)
    name = Column(String(64), nullable=False)
    level = Column(String(16), default="province")     # province / city / district
    pinyin = Column(String(128), default="")
    sort = Column(Integer, default=0)
    status = Column(Integer, default=1)


class Site(Base, TimestampMixin):
    """站点（主站 + 子站点）"""
    __tablename__ = "site"
    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, default=0)
    name = Column(String(128), nullable=False)
    code = Column(String(64), default="", index=True)
    domain = Column(String(500), default="")
    region_id = Column(Integer, default=0)
    is_master = Column(Integer, default=0)
    title_template = Column(String(255), default="")
    keywords = Column(Text, default="")
    description = Column(Text, default="")
    logo_id = Column(Integer, default=0)
    status = Column(Integer, default=1)
    theme = Column(String(64), default="default")
    render_mode = Column(String(24), default="dynamic")  # dynamic / pseudo_static / static
    static_out_dir = Column(String(255), default="")
    inherit_config = Column(Integer, default=1)
    config = Column(Text, default="{}")
    sort = Column(Integer, default=0)


class SiteVar(Base, TimestampMixin):
    """站点差异化变量"""
    __tablename__ = "site_var"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0, index=True)
    var_key = Column(String(64), default="")
    var_value = Column(Text, default="")


class SiteSyncLog(Base, TimestampMixin):
    """站群同步记录（无软删除）"""
    __tablename__ = "site_sync_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_no = Column(String(64), default="", index=True)
    source_site_id = Column(Integer, default=0)
    target_site_count = Column(Integer, default=0)
    mode = Column(String(24), default="content")        # content / config / seo
    strategy = Column(String(24), default="skip")       # skip / overwrite
    content_ids = Column(Text, default="[]")
    status = Column(String(16), default="success")      # success / partial / fail
    result = Column(Text, default="{}")


class SiteRegionMap(Base, TimestampMixin):
    """站点-地区映射"""
    __tablename__ = "site_region_map"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0, index=True)
    region_id = Column(Integer, default=0)
    province_id = Column(Integer, default=0)
    city_id = Column(Integer, default=0)
    district_id = Column(Integer, default=0)


# ==================== 7.3 多语言模型（无软删除） ====================
class Lang(Base, TimestampMixin):
    """语言定义"""
    __tablename__ = "lang"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    code = Column(String(16), default="zh-CN")
    name = Column(String(64), default="中文")
    is_default = Column(Integer, default=0)
    status = Column(Integer, default=1)
    sort = Column(Integer, default=0)


class LangPackage(Base, TimestampMixin):
    """公共语言包"""
    __tablename__ = "lang_package"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    lang_code = Column(String(16), default="zh-CN")
    key = Column(String(128), default="")
    value = Column(Text, default="")


# ==================== 7.4 内容模型 ====================
class ContentType(Base, TimestampMixin, SoftDeleteMixin):
    """内容类型"""
    __tablename__ = "content_type"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(64), default="")
    code = Column(String(64), default="", index=True)
    icon = Column(String(64), default="bi-file-earmark")
    is_comment = Column(Integer, default=0)
    is_order = Column(Integer, default=0)
    enable_tag = Column(Integer, default=1)
    fields = Column(Text, default="[]")
    list_view = Column(Text, default="{}")
    form_view = Column(Text, default="{}")
    status = Column(Integer, default=1)


class Category(Base, TimestampMixin, SoftDeleteMixin):
    """栏目分类（树形，软删除）"""
    __tablename__ = "category"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    content_type_id = Column(Integer, default=0)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), default="", index=True)
    model = Column(String(32), default="article")      # 兼容：article / product / case / page
    pid = Column(Integer, default=0, index=True)
    cover_id = Column(Integer, default=0)
    cover = Column(String(255), default="")            # 兼容：直接存 URL
    description = Column(Text, default="")
    template = Column(String(64), default="")
    is_nav = Column(Integer, default=1)
    privilege_json = Column(Text, default="[]")
    seo_title = Column(String(255), default="")
    seo_keywords = Column(String(255), default="")
    seo_description = Column(Text, default="")
    sort = Column(Integer, default=0)
    status = Column(Integer, default=1)


class Tag(Base, TimestampMixin, SoftDeleteMixin):
    """标签"""
    __tablename__ = "tag"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(64), nullable=False)
    sort = Column(Integer, default=0)
    status = Column(Integer, default=1)


class Content(Base, TimestampMixin, SoftDeleteMixin):
    """内容主表（软删除，主记录=默认语言）"""
    __tablename__ = "content"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    content_type_id = Column(Integer, default=0)
    category_id = Column(Integer, default=0, index=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(128), default="", index=True)
    subtitle = Column(String(255), default="")
    cover_id = Column(Integer, default=0)
    cover = Column(String(255), default="")
    summary = Column(Text, default="")
    body = Column(Text, default="")                    # 兼容：主内容
    main_content = Column(Text, default="")
    author = Column(String(64), default="")
    source = Column(String(64), default="")
    tags = Column(String(255), default="")
    is_top = Column(Integer, default=0)
    is_hot = Column(Integer, default=0)
    status = Column(String(16), default="publish")     # draft / publish / hidden
    view_count = Column(Integer, default=0)
    publish_at = Column(DateTime, nullable=True)
    seo_title = Column(String(255), default="")
    seo_keywords = Column(String(255), default="")
    seo_description = Column(Text, default="")
    sort = Column(Integer, default=0)
    extra = Column(Text, default="")                   # JSON 扩展字段
    model = Column(String(32), default="article", index=True)  # 兼容：article / product / case / page


class ContentLang(Base, TimestampMixin, SoftDeleteMixin):
    """多语言子表"""
    __tablename__ = "content_lang"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, default=0, index=True)
    lang_code = Column(String(16), default="en")
    title = Column(String(255), default="")
    main_content = Column(Text, default="")
    seo_title = Column(String(255), default="")
    seo_keywords = Column(String(255), default="")
    seo_description = Column(Text, default="")


class ContentAttr(Base, TimestampMixin, SoftDeleteMixin):
    """扩展字段"""
    __tablename__ = "content_attr"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, default=0, index=True)
    lang_code = Column(String(16), default="")
    field_key = Column(String(128), default="")
    field_value = Column(Text, default="")


class ContentTagRel(Base):
    """内容标签关联"""
    __tablename__ = "content_tag_rel"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, default=0, index=True)
    tag_id = Column(Integer, default=0, index=True)


# ==================== 7.5 会员模型（全部软删除） ====================
class MemberGroup(Base, TimestampMixin, SoftDeleteMixin):
    """会员分组"""
    __tablename__ = "member_group"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(64), default="")
    discount = Column(Integer, default=100)            # 0~100
    point_rate = Column(Numeric(10, 2), default=1)
    privilege = Column(Text, default="{}")
    status = Column(Integer, default=1)
    sort = Column(Integer, default=0)


class MemberLevel(Base, TimestampMixin, SoftDeleteMixin):
    """会员等级"""
    __tablename__ = "member_level"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(64), default="")
    min_point = Column(Integer, default=0)
    discount = Column(Integer, default=100)
    point_rate = Column(Numeric(10, 2), default=1)
    privilege = Column(Text, default="{}")
    icon = Column(String(255), default="")
    status = Column(Integer, default=1)
    sort = Column(Integer, default=0)


class Member(Base, TimestampMixin, SoftDeleteMixin):
    """会员"""
    __tablename__ = "member"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    group_id = Column(Integer, default=0)
    level_id = Column(Integer, default=0)
    username = Column(String(64), default="")
    mobile = Column(String(32), default="", index=True)
    email = Column(String(128), default="")
    password_hash = Column(String(255), default="")
    nickname = Column(String(64), default="")
    avatar = Column(String(255), default="")
    balance = Column(Numeric(12, 2), default=0)
    point = Column(Integer, default=0)
    total_consume = Column(Numeric(12, 2), default=0)
    status = Column(Integer, default=1)
    reg_ip = Column(String(64), default="")
    last_login_at = Column(DateTime, nullable=True)


class MemberAddress(Base, TimestampMixin, SoftDeleteMixin):
    """收货地址"""
    __tablename__ = "member_address"
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, default=0, index=True)
    name = Column(String(64), default="")
    mobile = Column(String(32), default="")
    province = Column(String(64), default="")
    city = Column(String(64), default="")
    district = Column(String(64), default="")
    detail = Column(String(255), default="")
    is_default = Column(Integer, default=0)


class MemberCollect(Base, TimestampMixin, SoftDeleteMixin):
    """收藏"""
    __tablename__ = "member_collect"
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, default=0, index=True)
    content_id = Column(Integer, default=0)


class MemberFootprint(Base, TimestampMixin, SoftDeleteMixin):
    """足迹"""
    __tablename__ = "member_footprint"
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, default=0, index=True)
    content_id = Column(Integer, default=0)


class MemberBalanceLog(Base, TimestampMixin, SoftDeleteMixin):
    """余额流水"""
    __tablename__ = "member_balance_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, default=0, index=True)
    type = Column(String(24), default="admin_adjust")   # recharge/order_pay/refund/admin_adjust
    amount = Column(Numeric(12, 2), default=0)
    before_balance = Column(Numeric(12, 2), default=0)
    after_balance = Column(Numeric(12, 2), default=0)
    related_no = Column(String(64), default="")
    remark = Column(Text, default="")


class MemberPointLog(Base, TimestampMixin, SoftDeleteMixin):
    """积分流水"""
    __tablename__ = "member_point_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, default=0, index=True)
    type = Column(String(24), default="admin_adjust")
    point = Column(Integer, default=0)
    before_point = Column(Integer, default=0)
    after_point = Column(Integer, default=0)
    related_no = Column(String(64), default="")
    remark = Column(Text, default="")


# ==================== 7.6 表单模型（软删除） ====================
class FormModel(Base, TimestampMixin, SoftDeleteMixin):
    """自定义表单"""
    __tablename__ = "form_model"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(128), nullable=False)
    code = Column(String(64), default="", index=True)
    fields = Column(Text, default="[]")
    is_notify = Column(Integer, default=0)
    notify_email = Column(String(255), default="")
    need_login = Column(Integer, default=0)            # 是否需要登录：1=必须登录后才能提交
    status = Column(Integer, default=1)


class FormRecord(Base, TimestampMixin, SoftDeleteMixin):
    """表单提交记录"""
    __tablename__ = "form_record"
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_model_id = Column(Integer, default=0, index=True)
    form_id = Column(Integer, default=0)               # 兼容
    member_id = Column(Integer, default=0)
    data = Column(Text, default="{}")
    ip = Column(String(64), default="")
    is_read = Column(Integer, default=0)
    read_at = Column(DateTime, nullable=True)


# ==================== 7.7 订单与库存模型（软删除） ====================
class ProductSku(Base, TimestampMixin, SoftDeleteMixin):
    """SKU 库存"""
    __tablename__ = "product_sku"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, default=0, index=True)
    sku_name = Column(String(128), default="")
    sku_spec = Column(Text, default="{}")
    stock = Column(Integer, default=0)
    price = Column(Numeric(12, 2), default=0)
    original_price = Column(Numeric(12, 2), default=0)
    image_id = Column(Integer, default=0)


class Order(Base, TimestampMixin, SoftDeleteMixin):
    """订单"""
    __tablename__ = "order"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    order_no = Column(String(64), default="", index=True)
    member_id = Column(Integer, default=0)
    amount = Column(Numeric(12, 2), default=0)
    pay_amount = Column(Numeric(12, 2), default=0)
    pay_status = Column(String(16), default="unpaid")  # unpaid / paid / refunded
    pay_time = Column(DateTime, nullable=True)
    pay_channel = Column(String(32), default="")
    pay_no = Column(String(64), default="")
    contact = Column(String(64), default="")
    mobile = Column(String(32), default="")
    address = Column(String(255), default="")
    remark = Column(Text, default="")
    status = Column(Integer, default=1)


class OrderItem(Base, TimestampMixin, SoftDeleteMixin):
    """订单明细"""
    __tablename__ = "order_item"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, default=0, index=True)
    content_id = Column(Integer, default=0)
    sku_id = Column(Integer, default=0)
    sku_info = Column(Text, default="{}")
    price = Column(Numeric(12, 2), default=0)
    num = Column(Integer, default=1)
    subtotal = Column(Numeric(12, 2), default=0)


class OrderRefund(Base, TimestampMixin, SoftDeleteMixin):
    """退款记录"""
    __tablename__ = "order_refund"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, default=0, index=True)
    refund_no = Column(String(64), default="")
    refund_amount = Column(Numeric(12, 2), default=0)
    reason = Column(Text, default="")
    status = Column(String(16), default="apply")       # apply/agree/reject/success
    audit_admin_id = Column(Integer, default=0)
    audit_at = Column(DateTime, nullable=True)
    success_at = Column(DateTime, nullable=True)


class StockLog(Base, TimestampMixin):
    """库存变动留痕"""
    __tablename__ = "stock_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, default=0)
    sku_id = Column(Integer, default=0)
    type = Column(String(16), default="deduct")        # lock/release/deduct/restore
    num = Column(Integer, default=0)
    before_stock = Column(Integer, default=0)
    after_stock = Column(Integer, default=0)
    related_no = Column(String(64), default="")


# ==================== 7.8 评论模型（软删除） ====================
class Comment(Base, TimestampMixin, SoftDeleteMixin):
    """评论"""
    __tablename__ = "comment"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    content_id = Column(Integer, default=0, index=True)
    member_id = Column(Integer, default=0)
    parent_id = Column(Integer, default=0)
    content = Column(Text, default="")
    nickname = Column(String(64), default="")
    contact = Column(String(64), default="")
    status = Column(String(16), default="pending")     # pending / pass / reject
    ip = Column(String(64), default="")


# ==================== 前台留言（业务补充） ====================
class Message(Base, TimestampMixin):
    """留言"""
    __tablename__ = "message"
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, default=0)
    name = Column(String(64), default="")
    phone = Column(String(32), default="")
    email = Column(String(128), default="")
    company = Column(String(128), default="")
    content = Column(Text, default="")
    ip = Column(String(64), default="")
    is_read = Column(Integer, default=0)
    status = Column(Integer, default=1)


# 兼容旧代码里的 Setting（站内设置，kept for backward-compat）
class Setting(Base):
    """站内设置（key-value）"""
    __tablename__ = "setting"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, default="")
    group = Column(String(64), default="basic")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Database:
    """每个站点一个独立 SQLite 连接。"""
    def __init__(self, db_file, echo: bool = False):
        self.db_file = str(db_file)
        self.engine = create_engine(
            f"sqlite:///{self.db_file}",
            connect_args={"check_same_thread": False},
            echo=echo,
        )

        # WAL 模式 + 常用 PRAGMA：读写并发不互相阻塞，前台访问不被后台写入卡住
        from sqlalchemy import event as _sa_event

        @_sa_event.listens_for(self.engine, "connect")
        def _sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA cache_size=-8000")
            cur.close()

        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """轻量迁移：为已有旧库补齐新增列（SQLite ALTER TABLE ADD COLUMN）。"""
        import sqlite3
        additions = {
            "admin_user": [
                ("mobile", "VARCHAR(32) DEFAULT ''"),
                ("email", "VARCHAR(128) DEFAULT ''"),
                ("last_login_ip", "VARCHAR(64) DEFAULT ''"),
                ("prev_login_ip", "VARCHAR(64) DEFAULT ''"),
                ("prev_login_at", "DATETIME"),
            ],
            "form_model": [
                ("need_login", "INTEGER DEFAULT 0"),
            ],
        }
        conn = sqlite3.connect(self.db_file)
        try:
            for table, cols in additions.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not existing:
                    continue
                for name, ddl in cols:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    def session(self):
        return self.SessionLocal()


# 全量模型注册表（供通用 CRUD / 菜单配置使用）
MODEL_REGISTRY = {
    "admin_user": AdminUser, "admin_role": AdminRole, "admin_permission": AdminPermission,
    "operation_log": OperationLog, "admin_config": AdminConfig, "media": Media,
    "admin_task": AdminTask, "admin_task_log": AdminTaskLog, "admin_backup": AdminBackup,
    "api_consumer": ApiConsumer,
    "region": Region, "site": Site, "site_var": SiteVar, "site_sync_log": SiteSyncLog,
    "site_region_map": SiteRegionMap,
    "lang": Lang, "lang_package": LangPackage,
    "content_type": ContentType, "category": Category, "tag": Tag, "content": Content,
    "content_lang": ContentLang, "content_attr": ContentAttr, "content_tag_rel": ContentTagRel,
    "member_group": MemberGroup, "member_level": MemberLevel, "member": Member,
    "member_address": MemberAddress, "member_collect": MemberCollect, "member_footprint": MemberFootprint,
    "member_balance_log": MemberBalanceLog, "member_point_log": MemberPointLog,
    "form_model": FormModel, "form_record": FormRecord,
    "product_sku": ProductSku, "order": Order, "order_item": OrderItem,
    "order_refund": OrderRefund, "stock_log": StockLog,
    "comment": Comment, "message": Message, "setting": Setting,
}
