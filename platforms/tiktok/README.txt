鼎峰 ERP — TikTok 平台
========================

platforms/tiktok/
├── shop/           店铺授权、shops.json、config_*.env、shop_hub.py
├── test_env/       API 客户端 tts_client.py、shop_tz.py
├── analytics/      数据分析（店铺分析.py）
├── orders/         订单查询
├── finance/        流水/结算
├── products/       商品管理（改价、库存、上下架）
├── promotions/     促销活动
└── content/        视频上传（Content Posting API）

Web 入口: web-portal/services/tiktok_auth.py
共用工具: erp/common/
