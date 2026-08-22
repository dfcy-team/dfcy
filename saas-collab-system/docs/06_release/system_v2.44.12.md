# SaaS 协同系统 V2.44.12 菜单恢复与 SPU-SKU 关联修复登记

- 登记日期：2026-08-13
- 父版本：V2.44.11
- 发布状态：已登记并部署（以虚拟机运行镜像为证）
- 恢复依据：V2.44.11 之后的 SPU-SKU 关联修复部署节点

## 菜单边界

V2.44.12 恢复该节点的完整菜单结构。一级菜单共 15 项，顺序、名称、权限分组及既有子菜单保持原配置；本次授权范围仅保留基础档案下的两项新增入口：

- 平台商品明细数据：`/products/platform-details`
- 国家信息：`/master-data/sites`

除上述两个基础档案授权入口外，不新增、删除、重排或改名其他菜单。达人管理沿用恢复节点已有配置。

## 关联修复证据

- 虚拟机前端镜像：`saas-collab-frontend:v2.44.12`
- 镜像创建时间：`2026-08-13T09:21:22Z`
- 菜单入口 bundle：`index-JtV9_d_m.js`
- 菜单入口 bundle SHA-256：`df255267267c9e8910e7ee363ce49dd3b770f6e58b7de69be9e76cdc28d9a9ba`
- 商品主数据 bundle：`ProductMasterList-BpPylCSL.js`
- 商品主数据 bundle SHA-256：`4577f5fb48df3ac9a8152d6d145fff6def56f1a36556ddd9b1bfc1ded16cb38a`
- 商品主数据 bundle 不再调用 `fetchProductSkuList` 或固定 `page_size:100`，改为使用 SPU 响应中的 `sku_codes` 关联数据。

## 验证

- 虚拟机容器：`application-frontend-1` 运行 `saas-collab-frontend:v2.44.12`
- bundle 含 15 个一级菜单：PASS
- bundle 含“平台商品明细数据”和“国家信息”：PASS
- SPU-SKU 关联 bundle 检查：PASS

