# -*- coding: utf-8 -*-
"""
鼎峰 TikTok Shop Web 平台
- 首页 / 控制台 / OAuth 回调 / 隐私政策
- 在线触发 Excel 导出并下载
"""
from __future__ import annotations

import sys
import re
import json
from pathlib import Path
from urllib.parse import quote, unquote

from datetime import timedelta

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

WEB_ROOT = Path(__file__).resolve().parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from services import auth, ads_exporter, content_video, exporter, files, marketing_auth, oauth, shops  # noqa: E402
from services.ads_refresh_scheduler import start_if_enabled as start_ads_refresh_scheduler  # noqa: E402
from services.settings import (  # noqa: E402
    APP_KEY,
    APP_SECRET,
    AUTHORIZE_URL,
    AUTO_EXCHANGE_TOKEN,
    CALLBACK_PATH,
    HOST,
    INFO_PATH,
    IS_LOCAL_DEV,
    PORT,
    PRODUCTION_AUTHORIZE_PAGE,
    PRODUCTION_CALLBACK_URL,
    PRODUCTION_PUBLIC_BASE,
    PROJECT_ROOT,
    REDIRECT_URL,
    LOGIN_REQUIRED,
    SECRET_KEY,
    SERVICE_ID,
    SITE_BRAND,
    SITE_DOMAIN,
    SITE_PUBLIC_BASE,
    COMPANY_NAME,
    CONTACT_EMAIL,
    CONTACT_ADDRESS,
)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=7)


@app.before_request
def _require_login():
    return auth.check_request_auth()


@app.context_processor
def inject_globals():
    return {
        "current_user": auth.get_current_user(),
        "login_enabled": LOGIN_REQUIRED,
        "brand": SITE_BRAND,
        "domain": SITE_DOMAIN,
        "site_base": SITE_PUBLIC_BASE,
        "authorize_url": AUTHORIZE_URL,
        "callback_url": REDIRECT_URL,
        "service_id": SERVICE_ID,
        "has_credentials": bool(APP_KEY and APP_SECRET),
        "is_local_dev": IS_LOCAL_DEV,
        "production_site": PRODUCTION_PUBLIC_BASE,
        "production_authorize_page": PRODUCTION_AUTHORIZE_PAGE,
        "production_callback_url": PRODUCTION_CALLBACK_URL,
        "project_root": str(PROJECT_ROOT),
        "company_name": COMPANY_NAME,
        "contact_email": CONTACT_EMAIL,
        "contact_address": CONTACT_ADDRESS,
    }


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if not LOGIN_REQUIRED:
        return render_template("login.html", login_disabled=True)
    if auth.get_current_user():
        return redirect(auth.safe_next_url(request.args.get("next")))
    error = ""
    username = ""
    next_url = auth.safe_next_url(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = auth.authenticate(username, password)
        if user:
            auth.login_user(user)
            return redirect(next_url)
        error = "用户名或密码错误"
    return render_template(
        "login.html",
        error=error,
        username=username,
        next_url=next_url,
    )


@app.get("/logout")
def logout():
    auth.logout_user()
    return redirect(url_for("index"))


def _guess_shop_for_callback(region: str) -> str:
    """无 state 时根据区域与当前 active 店猜测店键。"""
    region = (region or "").upper()
    try:
        import json
        from services.settings import SHOPS_JSON

        if SHOPS_JSON.is_file():
            data = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))
            active = (data.get("active") or "").strip().upper()
            if active:
                for s in data.get("shops") or []:
                    if s.get("key", "").upper() == active and s.get("platform") == "tiktok":
                        if not region or (s.get("region") or "").upper() == region:
                            return active
            if region == "TH":
                for key in ("TKKJ1TH", "TK1TH"):
                    for s in data.get("shops") or []:
                        if s.get("key", "").upper() == key and s.get("platform") == "tiktok":
                            return key
    except Exception:
        pass
    return "TKKJ1TH" if region == "TH" else ""


@app.route("/")
def index():
    shop_list = shops.load_shops()
    return render_template(
        "index.html",
        shops=shop_list,
        shop_count=len(shop_list),
        authorized_count=sum(1 for s in shop_list if s.get("has_token")),
    )


@app.route("/about")
@app.route("/about/")
def about():
    return render_template("about.html")


@app.route("/contact")
@app.route("/contact/")
def contact():
    return render_template("contact.html")


@app.route(INFO_PATH)
@app.route(INFO_PATH + "/")
def deploy_info():
    return render_template(
        "deploy.html",
        project_root=str(PROJECT_ROOT),
        listen=f"{HOST}:{PORT}",
    )


@app.route("/authorize")
def authorize_page():
    try:
        from shop_hub import ensure_all_registered_configs

        ensure_all_registered_configs()
    except Exception:
        pass
    auto_result = None
    if request.args.get("ok") == "1":
        auto_result = {
            "ok": True,
            "shop_key": request.args.get("shop", ""),
            "config": request.args.get("config", ""),
            "export_tag": request.args.get("tag", ""),
        }
    elif request.args.get("error"):
        auto_result = {"ok": False, "error": request.args.get("error", "")}
    return render_template(
        "authorize.html",
        shops=shops.load_shops(),
        auth_links=shops.list_tiktok_auth_links(),
        prefill_shop=request.args.get("shop", ""),
        prefill_callback=unquote(request.args.get("callback_url", "")),
        auto_result=auto_result,
    )


@app.get("/api/authorize-link")
def api_authorize_link():
    shop_key = (request.args.get("shop") or "").strip()
    if not shop_key:
        return jsonify({"ok": False, "error": "缺少 shop 参数"}), 400
    try:
        url = shops.build_authorize_url(shop_key)
        return jsonify({"ok": True, "url": url, "shop_key": shop_key.upper()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/setup-authorize")
def api_setup_authorize():
    data = request.get_json(force=True, silent=True) or {}
    shop_key = (data.get("shop_key") or "").strip()
    callback_url = (data.get("callback_url") or "").strip()
    pick = data.get("pick_index")
    if not shop_key or not callback_url:
        return jsonify({"ok": False, "error": "请填写店铺键和完整回调 URL"}), 400
    try:
        pick_i = int(pick) if pick not in (None, "", "null") else None
        result = shops.setup_and_authorize(
            shop_key,
            callback_url,
            pick_index=pick_i,
            export_tag=(data.get("export_tag") or "").strip(),
            shop_mode=(data.get("shop_mode") or "").strip(),
            create_if_missing=bool(data.get("create_if_missing", True)),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", shops=shops.load_shops())


@app.route("/ads")
@app.route("/ads/")
def ads_page():
    tok = marketing_auth.token_status()
    auth_ok = request.args.get("ok") == "1" and tok.get("authorized")
    auth_error = request.args.get("error", "")
    if request.args.get("ok") == "1" and not tok.get("authorized"):
        auth_error = auth_error or "授权回调完成但未保存 token，请重新点击「连接广告账户」"
    if tok.get("authorized") and auth_error:
        auth_error = ""
    cred_probe = marketing_auth.verify_credentials()
    shop_suggestions: list[dict[str, str]] = []
    seen_tags: set[str] = set()
    for s in shops.load_shops():
        tag = (s.get("export_tag") or s.get("label") or s.get("key") or "").strip()
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        shop_suggestions.append(
            {
                "key": s.get("key", ""),
                "tag": tag,
                "label": s.get("label", s.get("key", "")),
                "custom": False,
            }
        )
    custom_shops = marketing_auth.load_custom_ad_shops()
    for item in custom_shops:
        tag = (item.get("tag") or "").strip()
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        shop_suggestions.append(
            {
                "key": "",
                "tag": tag,
                "label": (item.get("note") or tag) + "（自定义）",
                "custom": True,
            }
        )
    return render_template(
        "ads.html",
        token=tok,
        bindings=tok.get("bindings") or [],
        bindings_json=json.dumps(tok.get("bindings") or [], ensure_ascii=False),
        auth_ok=auth_ok,
        auth_shop=request.args.get("shop", "").strip(),
        auth_error=auth_error,
        app_id=marketing_auth.APP_ID,
        redirect_uri=marketing_auth.REDIRECT_URI,
        credentials_ok=cred_probe.get("ok"),
        shop_suggestions=shop_suggestions,
        custom_shops=custom_shops,
    )


@app.route("/ads/authorize")
def ads_authorize():
    shop_name = (request.args.get("shop_name") or request.form.get("shop_name") or "").strip()
    if not shop_name:
        return redirect(url_for("ads_page", error="请先填写绑定店铺名"))
    session["ads_shop_label"] = shop_name
    url, _state = marketing_auth.build_authorize_url()
    return redirect(url)


@app.post("/api/ads/shop-label")
def api_ads_shop_label():
    tok = marketing_auth.token_status()
    if not tok.get("authorized"):
        return jsonify({"ok": False, "error": "请先完成广告账户授权"}), 400
    data = request.get_json(force=True, silent=True) or {}
    old_name = (data.get("old_shop_name") or data.get("shop_label") or "").strip()
    shop_name = (data.get("shop_name") or "").strip()
    if not shop_name:
        return jsonify({"ok": False, "error": "请填写店铺名"}), 400
    try:
        if old_name and old_name != shop_name:
            marketing_auth.save_shop_label(old_name, new_label=shop_name)
        elif old_name:
            marketing_auth.save_shop_label(old_name)
        else:
            marketing_auth.save_shop_label(shop_name)
        return jsonify({"ok": True, "shop_label": shop_name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/ads/custom-shops")
def api_ads_custom_shops_list():
    return jsonify({"ok": True, "shops": marketing_auth.load_custom_ad_shops()})


@app.post("/api/ads/custom-shops")
def api_ads_custom_shops_add():
    data = request.get_json(force=True, silent=True) or {}
    tag = (data.get("tag") or data.get("shop_name") or "").strip()
    note = (data.get("note") or "").strip()
    if not tag:
        return jsonify({"ok": False, "error": "请填写店铺名/导出标签"}), 400
    try:
        shops = marketing_auth.add_custom_ad_shop(tag, note=note)
        return jsonify({"ok": True, "shops": shops, "tag": tag})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.delete("/api/ads/custom-shops")
def api_ads_custom_shops_remove():
    data = request.get_json(force=True, silent=True) or {}
    tag = (data.get("tag") or data.get("shop_name") or request.args.get("tag") or "").strip()
    if not tag:
        return jsonify({"ok": False, "error": "请提供店铺名"}), 400
    try:
        shops = marketing_auth.remove_custom_ad_shop(tag)
        return jsonify({"ok": True, "shops": shops})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/ads/revoke")
def api_ads_revoke():
    data = request.get_json(force=True, silent=True) or {}
    shop_label = (data.get("shop_label") or "").strip()
    if not shop_label:
        return jsonify({"ok": False, "error": "请提供 shop_label"}), 400
    try:
        marketing_auth.delete_shop_authorization(shop_label)
        tok = marketing_auth.token_status()
        return jsonify(
            {
                "ok": True,
                "shop_label": shop_label,
                "binding_count": tok.get("binding_count") or 0,
                "authorized": bool(tok.get("authorized")),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/ads/refresh-advertisers")
def api_ads_refresh_advertisers():
    tok = marketing_auth.token_status()
    if not tok.get("authorized"):
        return jsonify({"ok": False, "error": "请先完成广告账户授权"}), 400
    data = request.get_json(force=True, silent=True) or {}
    shop_label = (data.get("shop_label") or request.args.get("shop_label") or "").strip()
    try:
        if shop_label:
            refreshed = marketing_auth.refresh_shop_advertisers(shop_label)
            return jsonify(
                {
                    "ok": True,
                    "shop_label": shop_label,
                    "advertiser_count": len(refreshed.get("advertisers") or []),
                    "default_advertiser_id": refreshed.get("default_advertiser_id", ""),
                    "advertisers": refreshed.get("advertisers") or [],
                }
            )
        results = marketing_auth.refresh_all_shop_advertisers()
        return jsonify({"ok": True, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/ads/default-advertiser")
def api_ads_default_advertiser():
    shop_label = (request.args.get("shop_label") or "").strip()
    if not shop_label:
        return jsonify({"ok": False, "error": "请提供 shop_label"}), 400
    if not marketing_auth.binding_for_shop(shop_label):
        return jsonify({"ok": False, "error": f"店铺「{shop_label}」尚未授权广告"}), 400
    adv_id = marketing_auth.resolve_default_advertiser_id(shop_label)
    return jsonify({"ok": True, "shop_label": shop_label, "advertiser_id": adv_id})


@app.post("/api/ads/export")
def api_ads_export():
    tok = marketing_auth.token_status()
    if not tok.get("authorized"):
        return jsonify({"ok": False, "error": "请先完成广告账户授权"}), 400
    data = request.get_json(force=True, silent=True) or {}
    shop_label = (data.get("shop_label") or "").strip()
    advertiser_id = (data.get("advertiser_id") or "").strip()
    start_date = (data.get("start_date") or "").strip()
    end_date = (data.get("end_date") or "").strip()
    report_kind = (data.get("report_kind") or "creative").strip().lower()
    if not shop_label:
        shop_label = (data.get("file_prefix") or tok.get("shop_label") or "").strip()
    file_prefix = (data.get("file_prefix") or shop_label or "ADS").strip() or "ADS"
    if not shop_label:
        return jsonify({"ok": False, "error": "请选择或填写绑定店铺名"}), 400
    if not marketing_auth.binding_for_shop(shop_label):
        return jsonify({"ok": False, "error": f"店铺「{shop_label}」尚未授权广告"}), 400
    if not advertiser_id:
        advertiser_id = marketing_auth.resolve_default_advertiser_id(shop_label)
    if not advertiser_id or not start_date or not end_date:
        return jsonify({"ok": False, "error": "请填写广告账户与日期范围（未选广告户时将自动使用卖家中心绑定户）"}), 400
    if report_kind not in ("creative", "live", "cost"):
        return jsonify({"ok": False, "error": "报表类型须为 creative、live 或 cost"}), 400
    try:
        job_id = ads_exporter.start_ads_export(
            advertiser_id=advertiser_id,
            start_date=start_date,
            end_date=end_date,
            report_kind=report_kind,
            file_prefix=file_prefix,
            shop_label=shop_label,
        )
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/ads/files")
def api_ads_files():
    from common.paths import EXPORT_ADS_DIR, ensure_export_dirs

    ensure_export_dirs()
    items = files.list_excel_files(limit=int(request.args.get("limit", 60)))
    roots = {
        str(EXPORT_ADS_DIR.resolve()),
        str((PROJECT_ROOT / "platforms" / "tiktok" / "marketing" / "exports").resolve()),
    }
    out = [f for f in items if str(Path(f["path"]).resolve()).startswith(tuple(roots))]
    return jsonify({"ok": True, "files": out})


@app.post("/api/ads/secret")
def api_ads_secret():
    data = request.get_json(silent=True) or {}
    secret = (data.get("secret") or request.form.get("secret") or "").strip()
    if not secret:
        return jsonify({"ok": False, "error": "请填写 App Secret"}), 400
    try:
        marketing_auth.save_app_secret(secret)
        probe = marketing_auth.verify_credentials()
        return jsonify({"ok": probe.get("ok"), "probe": probe})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/content")
def content_page():
    tok = content_video.token_status()
    auth_ok = request.args.get("ok") == "1" and tok.get("authorized")
    auth_error = request.args.get("error", "")
    if request.args.get("ok") == "1" and not tok.get("authorized"):
        auth_error = auth_error or "授权回调完成但未保存 token，请重新点击「连接 TikTok」"
    # 已有有效 token 时忽略「重新授权」失败提示，避免误导（可直接上传）
    if tok.get("authorized") and auth_error:
        auth_error = ""
    cred_probe = content_video.verify_credentials()
    return render_template(
        "content.html",
        token=tok,
        auth_ok=auth_ok,
        auth_error=auth_error,
        client_key=content_video.CLIENT_KEY,
        redirect_uri=content_video.REDIRECT_URI,
        credentials_ok=cred_probe.get("ok"),
    )


@app.route("/content/authorize")
def content_authorize():
    url, _state = content_video.build_authorize_url()
    return redirect(url)


@app.post("/api/content/secret")
def api_content_secret():
    data = request.get_json(silent=True) or {}
    secret = (data.get("secret") or request.form.get("secret") or "").strip()
    if not secret:
        return jsonify({"ok": False, "error": "请填写 Client Secret"}), 400
    try:
        content_video.save_client_secret(secret)
        probe = content_video.verify_credentials()
        return jsonify({"ok": probe.get("ok"), "probe": probe})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/content/exchange-url")
def api_content_exchange_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or request.form.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "请粘贴 TikTok 回调 URL"}), 400
    try:
        content_video.exchange_callback_url(url)
        tok = content_video.token_status()
        if not tok.get("authorized"):
            return jsonify({"ok": False, "error": "token 未保存"}), 400
        return jsonify({"ok": True, "open_id": tok.get("open_id"), "scope": tok.get("scope")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/content/upload")
def api_content_upload():
    if "video" not in request.files:
        return jsonify({"ok": False, "error": "请选择视频文件"}), 400
    f = request.files["video"]
    if not f.filename:
        return jsonify({"ok": False, "error": "文件名为空"}), 400
    mode = (request.form.get("mode") or "draft").strip().lower()
    title = (request.form.get("title") or "").strip()
    safe_name = re.sub(r"[^\w.\-]", "_", f.filename)[:120]
    dest = content_video.UPLOAD_DIR / safe_name
    f.save(dest)
    try:
        if mode == "direct":
            result = content_video.upload_direct(dest, title=title, privacy_level="SELF_ONLY")
        else:
            result = content_video.upload_draft(dest)
        return jsonify(
            {
                "ok": True,
                "publish_id": result.get("publish_id"),
                "mode": result.get("mode"),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass


@app.route("/terms")
@app.route("/terms/")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
@app.route("/privacy/")
def privacy():
    return render_template("privacy.html")


@app.route("/content/callback")
@app.route("/content/callback/")
def content_callback():
    """Content Posting API 专用 OAuth 回调（与 TikTok Shop /callback 分离）。"""
    error = request.args.get("error", "").strip()
    if error:
        return redirect(url_for("content_page", error=error))
    # 优先从原始 query string 取 code，避免解码问题
    code = content_video.extract_code_from_query(request.query_string) or request.args.get("code", "").strip()
    if code:
        try:
            content_video.exchange_code(code)
            if not content_video.token_status().get("authorized"):
                return redirect(url_for("content_page", error="token 保存失败，请重试"))
            return redirect(url_for("content_page", ok=1))
        except Exception as e:
            return redirect(url_for("content_page", error=str(e)))
    return redirect(url_for("content_page", error="未收到授权 code"))


@app.route(CALLBACK_PATH)
@app.route(CALLBACK_PATH + "/")
def callback():
    code = request.args.get("code", "").strip()
    error = request.args.get("error", "").strip()
    state_raw = request.args.get("state", "").strip()
    state = state_raw.upper()
    scopes = request.args.get("scopes", "").strip()
    app_key = request.args.get("app_key", "").strip()
    full_url = request.url

    auth_code = (
        marketing_auth.extract_auth_code_from_query(request.query_string)
        or request.args.get("auth_code", "").strip()
    )

    # TikTok Marketing API（auth_code 或 state=ads_*）
    if marketing_auth.is_marketing_callback(
        state_raw, auth_code, code=code, app_key=app_key, scopes=scopes
    ):
        if error:
            return redirect(url_for("ads_page", error=error))
        if auth_code:
            try:
                shop_label = (session.pop("ads_shop_label", None) or "").strip()
                marketing_auth.exchange_auth_code(auth_code, shop_label=shop_label)
                if not marketing_auth.token_status().get("authorized"):
                    return redirect(url_for("ads_page", error="token 保存失败，请重试"))
                qs = f"ok=1&shop={quote(shop_label)}" if shop_label else "ok=1"
                return redirect(url_for("ads_page") + "?" + qs)
            except Exception as e:
                return redirect(url_for("ads_page", error=str(e)))
        return redirect(url_for("ads_page", error="未收到 auth_code"))

    # TikTok Content Posting / Login Kit（带 scopes，无 app_key）
    if content_video.is_content_callback(state_raw, scopes, app_key):
        if error:
            return redirect(url_for("content_page", error=error))
        if code:
            try:
                content_video.exchange_code(code)
                if not content_video.token_status().get("authorized"):
                    return redirect(url_for("content_page", error="token 保存失败，请重试"))
                return redirect(url_for("content_page", ok=1))
            except Exception as e:
                return redirect(url_for("content_page", error=str(e)))
        return redirect(url_for("content_page"))

    # TikTok Shop OAuth
    if code and state and re.match(r"^[A-Z0-9_]+$", state) and not error:
        try:
            result = shops.setup_and_authorize(state, full_url, create_if_missing=True)
            return redirect(
                url_for(
                    "authorize_page",
                    ok=1,
                    shop=result["shop_key"],
                    config=result["config"],
                    tag=result.get("export_tag", ""),
                )
            )
        except Exception as e:
            return redirect(
                url_for(
                    "authorize_page",
                    error=str(e),
                    shop=state,
                    callback_url=quote(full_url, safe=""),
                )
            )

    if code and not state and not error:
        region = request.args.get("shop_region", "").strip().upper()
        shop_hint = _guess_shop_for_callback(region)
        return redirect(
            url_for(
                "authorize_page",
                error="回调缺少 state，请在下方选择店铺（如 TK1TH / TKKJ1TH）并点击「解析并保存授权」",
                shop=shop_hint,
                callback_url=quote(full_url, safe=""),
            )
        )

    return render_template(
        "callback.html",
        code=code,
        error=error,
        full_url=full_url,
        shops=shops.load_shops(),
        state=state,
    )


@app.post("/api/authorize-shop")
def api_authorize_shop():
    data = request.get_json(force=True, silent=True) or {}
    shop_key = (data.get("shop_key") or "").strip()
    callback_url = (data.get("callback_url") or "").strip()
    pick = data.get("pick_index")
    if not shop_key or not callback_url:
        return jsonify({"ok": False, "error": "缺少 shop_key 或 callback_url"}), 400
    try:
        pick_i = int(pick) if pick is not None else None
        result = shops.setup_and_authorize(
            shop_key,
            callback_url,
            pick_index=pick_i,
            create_if_missing=False,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/shops")
def api_shops():
    return jsonify({"shops": shops.load_shops()})


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True, silent=True) or {}
    kind = (data.get("kind") or "analytics").strip().lower()
    shop_key = (data.get("shop_key") or "").strip().upper()
    start_date = (data.get("start_date") or data.get("stat_day") or "").strip()
    end_date = (data.get("end_date") or data.get("stat_day") or start_date or "").strip()
    if not shop_key or not start_date or not end_date:
        return jsonify({"ok": False, "error": "请选择店铺和日期范围"}), 400
    try:
        if kind == "analytics":
            types = (data.get("types") or "all").strip()
            job_id = exporter.start_analytics_export(
                shop_key=shop_key,
                start_date=start_date,
                end_date=end_date,
                export_types=types,
            )
        elif kind == "finance":
            job_id = exporter.start_finance_export(
                shop_key=shop_key,
                start_date=start_date,
                end_date=end_date,
                finance_type=(data.get("finance_type") or "all").strip(),
            )
        elif kind == "orders":
            job_id = exporter.start_order_export(
                shop_key=shop_key, start_date=start_date, end_date=end_date
            )
        elif kind == "affiliate":
            job_id = exporter.start_affiliate_export(
                shop_key=shop_key, start_date=start_date, end_date=end_date
            )
        else:
            return jsonify({"ok": False, "error": f"未知导出类型: {kind}"}), 400
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    job = exporter.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    return jsonify({"ok": True, "job": job})


@app.get("/api/files")
def api_files():
    shop_key = (request.args.get("shop") or "").strip()
    items = files.list_excel_files(shop_key=shop_key, limit=int(request.args.get("limit", 80)))
    return jsonify({"ok": True, "files": items})


@app.get("/download")
def download():
    raw = unquote(request.args.get("path", "").strip())
    if not raw:
        return "缺少 path 参数", 400
    path = Path(raw)
    if not path.is_file() or not files.is_allowed_path(path):
        return "文件不存在或无权访问", 403
    return send_file(path, as_attachment=True, download_name=path.name)


def _tiktok_verification_file(filename: str):
    path = WEB_ROOT / "static" / filename
    if not path.is_file():
        return "verification file missing", 404
    return send_file(path, mimetype="text/plain")


@app.get("/tiktokBClAydS9vwVMKhSkOt0v09HSm31IysLe.txt")
def tiktok_site_verification_new():
    return _tiktok_verification_file("tiktokBClAydS9vwVMKhSkOt0v09HSm31IysLe.txt")


@app.get("/tiktok532RMdXks2KOBJkLG6f8cjy0gmhvYTUT.txt")
def tiktok_service_verification():
    return _tiktok_verification_file("tiktok532RMdXks2KOBJkLG6f8cjy0gmhvYTUT.txt")


@app.get("/tiktokpBXAw3JrjNFDmTYUFyaLFm11Mluq8vAK.txt")
def tiktok_terms_verification():
    return _tiktok_verification_file("tiktokpBXAw3JrjNFDmTYUFyaLFm11Mluq8vAK.txt")


@app.get("/privacy/tiktokoRH2kRDaeVaajfRtjDqaqnNPEnos3UCU.txt")
@app.get("/tiktokoRH2kRDaeVaajfRtjDqaqnNPEnos3UCU.txt")
def tiktok_privacy_verification():
    return _tiktok_verification_file("tiktokoRH2kRDaeVaajfRtjDqaqnNPEnos3UCU.txt")


@app.get("/privacy/tiktokJYHatFCahMnEtgVPcVRfpwJlgbjT8MRN.txt")
@app.get("/terms/tiktokJYHatFCahMnEtgVPcVRfpwJlgbjT8MRN.txt")
@app.get("/tiktokJYHatFCahMnEtgVPcVRfpwJlgbjT8MRN.txt")
def tiktok_site_verification_jyha():
    return _tiktok_verification_file("tiktokJYHatFCahMnEtgVPcVRfpwJlgbjT8MRN.txt")


@app.get("/terms/tiktoklphphpRqPXc1N6534Tvf3JqF33sCHgmk.txt")
@app.get("/tiktoklphphpRqPXc1N6534Tvf3JqF33sCHgmk.txt")
def tiktok_content_verification():
    return _tiktok_verification_file("tiktoklphphpRqPXc1N6534Tvf3JqF33sCHgmk.txt")


@app.get("/favicon.ico")
def favicon():
    return "", 204


def main() -> None:
    print(f"Listen {HOST}:{PORT}")
    print(f"Home:     http://127.0.0.1:{PORT}/")
    print(f"Dashboard http://127.0.0.1:{PORT}/dashboard")
    print(f"Authorize  http://127.0.0.1:{PORT}/authorize")
    print(f"Ads OAuth  http://127.0.0.1:{PORT}/ads")
    print(f"Deploy:   http://{SITE_DOMAIN}{INFO_PATH}")
    print(f"Callback: http://{SITE_DOMAIN}{CALLBACK_PATH}")
    print(f"Project:  {PROJECT_ROOT}")
    start_ads_refresh_scheduler()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
else:
    # 通过 gunicorn / import app 启动时同样加载内置调度
    start_ads_refresh_scheduler()
