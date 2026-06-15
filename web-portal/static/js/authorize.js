(function () {
  const shopKeySelect = document.getElementById("shop-key");
  const customWrap = document.getElementById("wrap-custom-key");
  const customKey = document.getElementById("custom-shop-key");
  const shopKeyPaste = document.getElementById("shop-key-paste");
  const customWrapPaste = document.getElementById("wrap-custom-key-paste");
  const customKeyPaste = document.getElementById("custom-shop-key-paste");
  const callbackUrl = document.getElementById("callback-url");
  const pickIndex = document.getElementById("pick-index");
  const createIfMissing = document.getElementById("create-if-missing");
  const callbackPreview = document.getElementById("callback-preview");
  const callbackResult = document.getElementById("callback-result");
  const formCallback = document.getElementById("form-callback-auth");

  function resolveShopKey(selectEl, customInput) {
    const v = (selectEl?.value || "").trim();
    if (v === "__custom__") {
      return (customInput?.value || "").trim().toUpperCase();
    }
    return v.toUpperCase();
  }

  function bindCustomToggle(selectEl, wrapEl) {
    selectEl?.addEventListener("change", () => {
      if (wrapEl) {
        wrapEl.style.display = selectEl.value === "__custom__" ? "" : "none";
      }
    });
    if (wrapEl && selectEl?.value === "__custom__") {
      wrapEl.style.display = "";
    }
  }

  bindCustomToggle(shopKeySelect, customWrap);
  bindCustomToggle(shopKeyPaste, customWrapPaste);

  document.querySelectorAll(".auth-link-chip").forEach((link) => {
    link.addEventListener("click", () => {
      const k = (link.getAttribute("data-key") || "").toUpperCase();
      if (shopKeySelect) shopKeySelect.value = k;
      if (shopKeyPaste) shopKeyPaste.value = k;
    });
  });

  async function fetchAuthLink(key) {
    const r = await fetch("/api/authorize-link?shop=" + encodeURIComponent(key));
    return r.json();
  }

  async function openTikTokAuth(key) {
    if (!key) {
      alert("请先选择或填写店铺");
      return;
    }
    const data = await fetchAuthLink(key);
    if (data.ok) {
      window.location.href = data.url;
    } else {
      alert(data.error || "无法打开授权页");
    }
  }

  document.getElementById("btn-open-tiktok")?.addEventListener("click", async () => {
    await openTikTokAuth(resolveShopKey(shopKeySelect, customKey));
  });

  document.querySelectorAll(".open-auth-shop").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const k = (btn.getAttribute("data-key") || "").toUpperCase();
      if (shopKeySelect) shopKeySelect.value = k;
      if (shopKeyPaste) shopKeyPaste.value = k;
      await openTikTokAuth(k);
    });
  });

  function parseCallbackUrl(raw) {
    const text = (raw || "").trim();
    if (!text) return null;
    try {
      const u = text.includes("://") ? new URL(text) : new URL(text, window.location.origin);
      return {
        app_key: u.searchParams.get("app_key") || "",
        code: u.searchParams.get("code") || "",
        shop_region: u.searchParams.get("shop_region") || "",
        locale: u.searchParams.get("locale") || "",
        state: u.searchParams.get("state") || "",
        error: u.searchParams.get("error") || "",
      };
    } catch (e) {
      return { error: "URL 格式无效" };
    }
  }

  function renderPreview(info) {
    if (!callbackPreview) return;
    if (!info) {
      callbackPreview.textContent = "";
      return;
    }
    if (info.error && !info.code) {
      callbackPreview.className = "alert";
      callbackPreview.textContent = info.error;
      return;
    }
    callbackPreview.className = "muted";
    const codeTail = info.code ? info.code.slice(-12) : "";
    callbackPreview.innerHTML =
      "<strong>解析预览</strong><ul style=\"margin:6px 0 0 1.2em;\">" +
      "<li>app_key: <code>" + (info.app_key || "—") + "</code></li>" +
      "<li>code: " + (info.code ? "已识别（…" + codeTail + "）" : "<span class=\"alert\">未找到</span>") + "</li>" +
      "<li>shop_region: <code>" + (info.shop_region || "—") + "</code></li>" +
      "<li>state: <code>" + (info.state || "无（需手动选店铺）") + "</code></li>" +
      "</ul>";
  }

  document.getElementById("btn-preview-url")?.addEventListener("click", () => {
    renderPreview(parseCallbackUrl(callbackUrl?.value));
  });

  if (callbackUrl?.value?.trim()) {
    renderPreview(parseCallbackUrl(callbackUrl.value));
  }

  formCallback?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const shopKey = resolveShopKey(shopKeyPaste, customKeyPaste);
    const url = (callbackUrl?.value || "").trim();
    if (!shopKey) {
      alert("请选择店铺");
      return;
    }
    if (!url) {
      alert("请粘贴回调 URL");
      return;
    }
    const info = parseCallbackUrl(url);
    if (!info?.code) {
      alert("URL 中未找到 code 参数");
      return;
    }
    if (callbackResult) {
      callbackResult.className = "muted";
      callbackResult.textContent = "正在解析并保存授权…";
    }
    try {
      const body = {
        shop_key: shopKey,
        callback_url: url,
        create_if_missing: !!createIfMissing?.checked,
      };
      const pick = (pickIndex?.value || "").trim();
      if (pick !== "") body.pick_index = parseInt(pick, 10);
      const r = await fetch("/api/setup-authorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (data.ok) {
        callbackResult.className = "ok";
        callbackResult.innerHTML =
          "<p><strong>授权成功</strong> 店铺 <code>" +
          data.shop_key +
          "</code>，配置 <code>" +
          (data.config || data.created_config || "") +
          "</code></p>" +
          "<p><a class=\"btn primary\" href=\"" +
          "/dashboard\">去导出数据</a></p>";
        renderPreview(info);
      } else {
        callbackResult.className = "alert";
        callbackResult.textContent = "失败：" + (data.error || "未知错误");
      }
    } catch (err) {
      if (callbackResult) {
        callbackResult.className = "alert";
        callbackResult.textContent = String(err);
      }
    }
  });
})();
