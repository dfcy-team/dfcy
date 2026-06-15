鼎峰TK内容管家 — 视频上传（TikTok Content Posting API）
====================================================

应用：视频上传沙盒 / 鼎峰TK内容管家
Client Key: sbaw5qeahefu7vcr2t

第一步：配置凭据
----------------
1. copy app.env.example → app.env
2. 在 TikTok Developer Portal 复制 Client Secret 填入 app.env

第二步：Sandbox 添加测试用户
----------------------------
Developer Portal → Sandbox settings → 添加你的 TikTok 账号为测试用户

第三步：Web 授权 + 上传
------------------------
1. 打开 https://dingfengchuangyu.top/content
2. 点「连接 TikTok」完成 Login Kit 授权
3. 选择 mp4 视频 → 上传草稿 或 直接发布

命令行
------
cd 视频上传
python 上传视频.py status          # 查看授权
python 上传视频.py auth-url         # 打印授权链接
python 上传视频.py draft 视频.mp4   # 上传草稿
python 上传视频.py direct 视频.mp4 --title "标题"  # 直发
python 上传视频.py poll <publish_id>  # 查状态

Partner 配置（你已填）
----------------------
- Web URL: https://dingfengchuangyu.top/
- Terms: https://dingfengchuangyu.top/terms
- Privacy: https://dingfengchuangyu.top/privacy
- Redirect URI: https://dingfengchuangyu.top/callback
- Scopes: user.info.basic, video.upload, video.publish

注意
----
- 草稿上传用 video.upload，进 TikTok App 收件箱
- 直接发布用 video.publish，沙盒建议 privacy=SELF_ONLY
- token 保存在 视频上传/tokens/user_token.json
