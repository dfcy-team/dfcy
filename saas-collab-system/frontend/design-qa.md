# 用户目录与角色权限设计验收

final result: passed

验收时间：2026-10-02；本次选择为用户确认的第 1 张“模块导航工作区”。
实现地址：http://127.0.0.1:5190/system/users （本地真实 API、隔离 SQLite 验收数据）。

## 视觉依据与比较状态

证据目录：D:/Users/Administrator/Documents/saas协同系统/.codex-work/permission-ui-design-20261001

| 页面 | source visual truth path | implementation screenshot path | state |
| --- | --- | --- | --- |
| 角色权限 | design-1.png | 13-role-editor-reference-state.jpg | 配置抽屉、基础档案、功能操作、未筛选 |
| 用户目录 | design-1-user-directory.png | 07-user-directory-desktop.jpg | 全部可见用户、更多操作展开 |
| 有效权限 | design-1-effective-permissions.png | 08-effective-permissions-desktop.jpg | 有效权限页签、用户字段来源详情展开 |

以上源图与实现图均为 1487 × 1058 像素，CSS viewport 1487 × 1058，图片像素与 CSS 大小比 1:1，不进行密度缩放。
用户、角色、授权数量采用真实本地验收数据，替换参考图中的示例数据；因此不做逐像素相似度声明。
有效权限实现图使用“用户”筛选以检查字段与来源，源图为示例混合权限；布局与详情层级比较，记录数差异不作为视觉缺陷。

full-view comparison evidence：qa-comparison-role.png、qa-comparison-users.png、qa-comparison-effective.png，源图和浏览器截图拼合在同一比较图中。
focused region comparison evidence：qa-comparison-role-detail.png，900px 抽屉的标题、筛选和首个权限卡片在原尺寸并列比较；有效权限详情在全图原尺寸可读，无需再裁剪。

## Findings 与修正历史

1. [P2，已修正] 角色卡片继承 checkbox-group 的零行高造成标题与说明重叠。
   修正：显式 14px / 1.5 行高并将卡片标题、完整勾选行分层；修正后 05、06、13 图无重叠。
2. [P2，已修正] 抽屉经 Teleport 后带作用域的外层选择器未生效，标题与正文间距过大，权限正文层级偏弱。
   首次比较：qa-comparison-role-iteration1.png、qa-comparison-role-detail-iteration1.png、qa-comparison-effective-iteration1.png。
   修正：仅对 permission-editor/effective-drawer 使用独立全局外层选择器；桌面 header 24px / 下边距 12px、body 12px 24px，权限主文字 16px，手机 14px。
   复验：13-role-editor-reference-state.jpg、08-effective-permissions-desktop.jpg；浏览器读取实际 header/body 样式与 16px 字号相符。
3. [P1，已修正] 用户“更多”触发列表行事件而同时打开资料详情。
   修正：实际下拉触发按钮阻止冒泡。07 图只有操作菜单，选择有效权限后仅打开目标抽屉。
4. [P1，已修正] 批量预览把新增/移除/保留的权限编码当作角色显示。
   修正：角色列独立显示名称，权限列显示数量及中文弹出明细；11-authorization-preview-tablet.jpg 显示正确的 2 项收回权限。
5. [P2，已修正] 工作台模拟中的全范围对象进入自定义配置格式化。
   修正：显式 scope_type=all 先显示“租户全部范围”；14-workbench-simulation-tablet.jpg 为全新页面重新请求后的正确结果。
6. [P1，已修正] 切换用户时异步权限查询可能回填旧用户数据。
   修正：用户 ID 与请求序列守卫，重开抽屉清空模拟状态。最终独立契约审查 U9 无阻塞项。

## Required fidelity surfaces

- Fonts / typography：沿用产品系统中文字体回退，抽屉标题 22px，卡片标题与主权限名称 16px，说明 13–14px；手机标题 18px、权限 14px，行高明确，无截断/重叠。
- Spacing / layout rhythm：角色抽屉 900px、业务导航 215px；卡片边界、筛选行、固定操作页脚与参考方向一致。有效权限 1080px，为真实五列和多来源信息留出空间；小屏改模块下拉与纵向条目。
- Colors / tokens：白色工作区、蓝色选中/主操作、浅灰蓝边框和卡片标题区；高风险使用产品警告色，停用使用灰色，结果与来源分离。
- Image quality / assets：本次是数据管理 UI，无照片/插画资产；保留产品已有导航，控件图标使用现有 Element Plus 图标，没有手工绘制替代素材。
- Copy / content：400 项权限编码均有中文显示名称；权限类型、来源、范围、状态为中文。技术编码只在搜索输入、角色系统标识和展开详情中保留。实际业务目录和原有安全边界优先于示例图。

## 操作与响应式验收

- 桌面 1487×1058：用户详情/更多菜单/角色分配框、角色模块切换、功能页、搜索、仅看已选、新增计数、快速与逐项模式切换、历史授权、资源范围取消。
- 手机 390×844：06-role-editor-mobile.jpg、09-effective-permissions-mobile.jpg；筛选、勾选、模块下拉、分页及取消/保存入口可操作、可见。
- 平板 768×1024：10-simulation-tablet.jpg、11-authorization-preview-tablet.jpg、14-workbench-simulation-tablet.jpg；只读模拟允许结果、全范围、来源、批量预览完整。
- 更改批量条件后旧预览提交按钮自动禁用；本地浏览器只生成预览，未提交离职或权限写入。
- 权限列表默认不展示停用模块；打开“查看停用项”后显示“模块停用”，不更改接口的 allowed 值。365 原始授权中默认显示 258 项，开发项目筛选显示 3 个历史停用条目。
- 浏览器 error 级日志复验为空；已有 Element Plus small 分页弃用提示属于 P3，不影响功能。

## 工程检查与边界

前端初始全套 898/898 通过；重放到当前主干 3c4e74d 后全套 915/915 通过；生产构建通过；菜单快照 108 项与路由 142 项一致。
后端权限复制、停用授权、新增授权、高风险确认、模块门禁、权限目录等针对性检查 31/31 通过。
生产用户数据、原有授权和模块启停状态不批量修改；无数据库迁移，API 英文编码保持稳定。
真实提交、部署和版本登记的最终验收另见发布控制回执，本报告不代替生产部署证明。
资源范围编辑器合并保留当前主干的商品范围搜索与已选项回填；权限目录仍为 400 项，新增授权安全逻辑与商品范围接口均经独立兼容审查。

## Follow-up polish（P3）

少数历史权限说明可进一步消除重复词；无姓名的账号可能在主次行重复显示。保留当前产品导航及 Element Plus 标准控件尺寸，未替换全局品牌和其它模块。
无未完成 P0/P1/P2 项。

## Implementation checklist

- [x] 选定第 1 张并实现现有 Vue 页面
- [x] 真实 API 与核心内部操作验收
- [x] 全视图与重点区域源图/实现同图比较
- [x] 桌面、平板、手机复验
- [x] 可验收缺陷修正并保留复验图
- [x] 保存本报告；生产发布单独记录
