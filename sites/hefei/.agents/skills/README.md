# 站点运维 Skills

本目录存放当前站点（自包含单站）供 AI Agent / 运维脚本复用的技能说明。
五站目录结构完全一致，站点差异仅存在于 `storage/`（唯一持久化目录，容器只挂这一个卷）。

## 可用技能

### 1. 站点健康检查
- 入口：根目录 `scripts/pysite status`
- 校验：`GET /api/health` 返回 200 且 `status=ok`
- 前台首页 `GET /`、`GET /sitemap.xml` 均返回 200

### 2. 内容模型与数据
- 内容模型：后台「开发管理 → 内容模型」，模型可增删改查
- `sitemap.xml` 是系统内置功能（非内容模型）：按栏目与已发布内容动态生成，不落地静态文件
- 上传文件与主题库由 nginx 直出（见项目根 `scripts/nginx/`），应用侧路由仅作本地兜底

### 3. 缓存与静态版本
- 前台整页缓存：`storage/cache/pages/`
- 后台变更联动清缓存；静态资源版本号存于 `Setting.static_version`

### 4. 数据保护
- 数据库：`storage/site.db`，严禁纳入 Git
- 上传文件：`storage/uploads/`（仅 `.gitkeep` 入库）
- 部署脚本会在 `git reset` 前备份以上目录并回滚合并

## 目录约定

```
<site>/
├── .agents/skills/   本文件：Agent/运维技能说明
├── docs/             站点结构与维护文档
├── tests/            冒烟测试脚本
├── api/ core/ frontend/ admin/   程序代码（五站一致）
├── themes/           主题
├── storage/             唯一持久化目录：site.db / seed.json / uploads / cache / logs / sessions / temp
├── scripts/          站点运维脚本
└── site.json         站点配置
```
