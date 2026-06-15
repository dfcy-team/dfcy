商品管理 — 单独运行说明
========================

配置: 改本目录 **商品配置.ini**（不是 导入总配置.ini）

默认店铺在 [common] shop = TK6PH
也可命令行覆盖: --shop TK2PH


一、改配置
----------
  商品配置.ini
    [common] shop / dry_run
    [price]          改价 ID
    [product_listing] 上下架
    [sku_listing]    SKU 上架
    [inventory]      改库存
    [create]         创建商品
    [excel_create]   Excel 批量创建


二、常用命令（在本目录执行）
----------------------------
  运行商品查询.bat              查商品列表
  运行产品改价.bat              改 SKU 价格
  运行上下架.bat                商品上架/下架
  运行改库存.bat                改库存
  run_create.bat                创建商品（读 [create]）
  run_excel_create.bat          Excel 批量创建
  run_excel_create.bat --execute   真实创建
  run_product_activate.bat      已有商品上架
  run_sync_categories.bat       同步 PH 类目


三、示例
--------
  python 产品改价.py --shop TK6PH
  python Excel创建商品.py --shop TK6PH --execute
  python 上下架.py --shop TK6PH --activate --product-id 1735...


四、注意
--------
  dry_run = 1 只预览，不写 API
  dry_run = 0 真实调用
  PH 店标题/描述请用英文

店铺 env 位置: ..\店铺配置\config_<店键>.env
