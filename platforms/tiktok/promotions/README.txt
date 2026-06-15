促销模块 — TikTok Shop Promotion API
=====================================

权限（Partner Center 勾选后店铺需重新授权）:
  查: seller.promotion.info
  改: seller.promotion.write

配置: 促销配置.ini
  [common] shop / dry_run（1=只预览不写 API）
  各脚本对应段落填 activity_id、product_id、sku_id 等

查询
  运行查促销.bat
  python 查促销.py --shop TKKJ3PH --save --detail 5
  日志: logs/<店铺>/promotion_query_*.json

创建活动（先建空活动，再加商品）
  1. 填 [创建活动] title / activity_type / begin_time / end_time
  2. 运行创建活动.bat          （dry_run 预览）
  3. 运行创建活动.bat --execute （真实创建）
  4. 把返回的 activity_id 写到 [活动加商品]

活动加商品
  填 [活动加商品] activity_id, product_id, sku_id, activity_price_amount（或 discount）
  运行活动加商品.bat --execute

更新 / 停用 / 移除商品
  运行更新活动.bat / 运行停用活动.bat / 运行活动移除商品.bat
  加 --execute 才会调用写接口

活动类型: FIXED_PRICE | FLASHSALE | DIRECT_DISCOUNT
级别: PRODUCT | VARIATION（PH 店多为 VARIATION，需 sku_id）

时间格式: 2026-06-10 00:00（按店铺当地时区，如 PH=Asia/Manila）
