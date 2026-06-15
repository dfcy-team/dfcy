店铺配置（多店 token / env）
========================

目录: TikTok_API\正式环境\店铺配置\

文件说明
--------
  app.env              应用 app_key / secret（全部店共用）
  shops.json           店铺注册表（10 家店，含 TKKJ5PH）
  config_<店键>.env    每店 token / cipher / 导出标签
  CURRENT_SHOP.txt     未指定 --shop 时的默认店
  shop_hub.py          多店逻辑（授权、切换、新建）

已配置店铺
----------
  TK1PH, TK2PH, TK3PH, TK4PH, TK6PH, TK7PH, TK8PH
  TKKJ1PH, TKKJ3PH, TKKJ5PH

常用操作
--------
  切换默认店:
    python 切换店铺.py TK6PH

  新店授权生成 env:
    python 生成店铺env.py TKKJ6PH "授权回调URL"

  查看全部店状态:
    python shop_hub.py

注意: env 含 token，勿外传。
