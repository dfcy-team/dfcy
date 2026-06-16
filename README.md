# 鼎峰 ERP

TikTok Shop / Shopee 数据平台与授权管理。

## 目录结构

```
erp/
├── common/                 共用工具（路径、Excel、MySQL、配置加载）
├── config/                 批量导入 ini 配置
├── platforms/
│   ├── tiktok/             TikTok 全部代码
│   └── shopee/             Shopee（待开发）
└── web-portal/             统一网站（登录、授权、导出）
```

## 启动

| 脚本 | 说明 |
|------|------|
| `启动网站.bat` | 本机 http://127.0.0.1:8080 |
| `启动HTTPS服务.bat` | Flask + Nginx → https://dingfengchuangyu.top |

## 首次配置

1. 复制 `web-portal/local.env.example` 为 `web-portal/local.env`
2. 复制 `platforms/tiktok/content/app.env.example` 为 `platforms/tiktok/content/app.env` 并填写密钥
3. 复制 `platforms/tiktok/marketing/app.env.example` 为 `platforms/tiktok/marketing/app.env` 并填写 App Secret
4. 店铺授权后会在 `platforms/tiktok/shop/` 生成 `config_*.env`（已在 .gitignore 中，不会上传）

详细说明见各子目录 `README.txt`。
