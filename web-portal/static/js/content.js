(function () {
  const form = document.getElementById("form-upload");
  const result = document.getElementById("upload-result");
  const btnDraft = document.getElementById("btn-upload-draft");
  const btnDirect = document.getElementById("btn-upload-direct");
  const secretForm = document.getElementById("form-secret");
  const secretResult = document.getElementById("secret-result");

  const modeLabel = {
    draft: "草稿（收件箱）",
    direct: "直接发布",
  };

  async function doUpload(mode) {
    if (!form) return;
    const fileInput = form.querySelector('input[name="video"]');
    if (!fileInput?.files?.length) {
      result.className = "alert";
      result.textContent = "请先选择视频文件";
      return;
    }
    const fd = new FormData(form);
    fd.set("mode", mode);
    result.className = "muted";
    result.textContent = mode === "draft" ? "草稿上传中，请稍候…" : "直接发布中，请稍候…";
    btnDraft?.setAttribute("disabled", "disabled");
    btnDirect?.setAttribute("disabled", "disabled");
    try {
      const r = await fetch("/api/content/upload", { method: "POST", body: fd });
      const data = await r.json();
      if (data.ok) {
        result.className = "ok";
        const label = modeLabel[data.mode] || data.mode;
        result.innerHTML =
          "<p><strong>成功</strong> publish_id: <code>" +
          data.publish_id +
          "</code></p>" +
          "<p>模式: " +
          label +
          " (" +
          data.mode +
          ")</p>" +
          (data.mode === "draft"
            ? "<p class=\"muted\">请到 TikTok App → 收件箱 → 系统通知查看。</p>"
            : "<p class=\"muted\">请到 TikTok App → 个人主页查看（沙盒默认仅自己可见）。</p>");
      } else {
        result.className = "alert";
        result.textContent = "失败：" + (data.error || "未知错误");
      }
    } catch (err) {
      result.className = "alert";
      result.textContent = String(err);
    } finally {
      btnDraft?.removeAttribute("disabled");
      btnDirect?.removeAttribute("disabled");
    }
  }

  btnDraft?.addEventListener("click", () => doUpload("draft"));
  btnDirect?.addEventListener("click", () => doUpload("direct"));

  form?.addEventListener("submit", (e) => e.preventDefault());

  secretForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const secret = secretForm.secret?.value?.trim();
    if (!secret) return;
    secretResult.className = "muted";
    secretResult.textContent = "保存并验证中…";
    try {
      const r = await fetch("/api/content/secret", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ secret }),
      });
      const data = await r.json();
      if (data.ok) {
        secretResult.className = "ok";
        secretResult.textContent = "Secret 已保存，TikTok 已接受此凭据。请点「连接 TikTok」重新授权。";
      } else {
        secretResult.className = "alert";
        secretResult.textContent = "失败：" + (data.error || data.probe?.detail || "凭据无效");
      }
    } catch (err) {
      secretResult.className = "alert";
      secretResult.textContent = String(err);
    }
  });
})();
