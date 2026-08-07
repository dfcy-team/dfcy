(() => {
  const shell = document.querySelector(".publisher-shell");
  const form = document.getElementById("form-upload");
  const fileInput = document.getElementById("video-file");
  const preview = document.getElementById("video-preview");
  const empty = document.getElementById("video-empty");
  const videoMeta = document.getElementById("video-meta");
  const directFields = document.getElementById("direct-fields");
  const privacy = document.getElementById("privacy-level");
  const publishButton = document.getElementById("btn-publish");
  const result = document.getElementById("upload-result");
  const modeHelp = document.getElementById("mode-help");
  const caption = form?.querySelector('[name="title"]');
  const captionCount = document.getElementById("caption-count");
  const consentText = document.getElementById("consent-text");
  const commercialToggle = form?.querySelector('[name="commercial_toggle"]');
  const commercialOptions = document.getElementById("commercial-options");
  const brandOrganic = form?.querySelector('[name="brand_organic"]');
  const brandContent = form?.querySelector('[name="brand_content"]');
  const commercialLabel = document.getElementById("commercial-label");

  let creatorInfo = null;
  let videoObjectUrl = "";
  let videoDuration = 0;
  let statusTimer = null;

  const privacyLabels = {
    PUBLIC_TO_EVERYONE: "Everyone",
    FOLLOWER_OF_CREATOR: "Followers",
    MUTUAL_FOLLOW_FRIENDS: "Friends",
    SELF_ONLY: "Only me",
  };

  function selectedMode() {
    return form?.querySelector('[name="publish_mode"]:checked')?.value || "draft";
  }

  function setResult(kind, html) {
    if (!result) return;
    result.hidden = false;
    result.className = `publish-result ${kind}`;
    result.innerHTML = html;
  }

  function updateMode() {
    const direct = selectedMode() === "direct";
    directFields.hidden = !direct;
    publishButton.textContent = direct ? "Post to TikTok" : "Send to TikTok drafts";
    modeHelp.textContent = direct
      ? "Your selections below will be used for this direct post."
      : "TikTok will send an inbox notification so you can finish editing and publish in the TikTok app.";
    updateCommercialState();
    privacy.required = direct;
  }

  function updateCommercialState() {
    const enabled = Boolean(commercialToggle?.checked);
    if (commercialOptions) commercialOptions.hidden = !enabled;
    if (!enabled) {
      if (brandOrganic) brandOrganic.checked = false;
      if (brandContent) brandContent.checked = false;
    }

    const branded = Boolean(brandContent?.checked);
    const ownBrand = Boolean(brandOrganic?.checked);
    const privateOption = Array.from(privacy?.options || []).find((option) => option.value === "SELF_ONLY");
    if (privateOption) privateOption.disabled = branded;
    if (branded && privacy?.value === "SELF_ONLY") privacy.value = "";

    if (commercialLabel) {
      commercialLabel.textContent = branded
        ? "Your video will be labeled as 'Paid partnership'. Branded content cannot use Only me visibility."
        : ownBrand
          ? "Your video will be labeled as 'Promotional content'."
          : enabled
            ? "Select Your brand, Branded content, or both."
            : "";
    }
    if (consentText) {
      consentText.textContent = selectedMode() === "direct"
        ? branded
          ? "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
          : "By posting, you agree to TikTok's Music Usage Confirmation."
        : "I reviewed this video and explicitly consent to send it to my TikTok inbox drafts.";
    }
  }

  function renderCreator(info) {
    creatorInfo = info;
    document.getElementById("creator-loading").hidden = true;
    document.getElementById("creator-card").hidden = false;
    document.getElementById("creator-avatar").src = info.creator_avatar_url || "";
    document.getElementById("creator-nickname").textContent = info.creator_nickname || "TikTok creator";
    document.getElementById("creator-username").textContent =
      info.creator_username ? `@${info.creator_username}` : "";

    privacy.innerHTML = '<option value="">Select privacy setting</option>';
    (info.privacy_level_options || []).forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = privacyLabels[value] || value;
      privacy.appendChild(option);
    });
    updateCommercialState();

    const interactionRules = [
      ["allow_comment", "comment_disabled"],
      ["allow_duet", "duet_disabled"],
      ["allow_stitch", "stitch_disabled"],
    ];
    interactionRules.forEach(([inputName, disabledKey]) => {
      const input = form.querySelector(`[name="${inputName}"]`);
      input.checked = false;
      input.disabled = Boolean(info[disabledKey]);
      input.closest("label").classList.toggle("disabled", input.disabled);
    });
  }

  async function loadCreator() {
    if (shell?.dataset.authorized !== "true") return;
    try {
      const response = await fetch("/api/content/creator");
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Creator information is unavailable");
      renderCreator(data.creator);
    } catch (error) {
      document.getElementById("creator-loading").hidden = true;
      const errorBox = document.getElementById("creator-error");
      errorBox.hidden = false;
      errorBox.textContent = String(error.message || error);
      form.querySelector("fieldset").disabled = true;
    }
  }

  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (videoObjectUrl) URL.revokeObjectURL(videoObjectUrl);
    videoObjectUrl = URL.createObjectURL(file);
    preview.src = videoObjectUrl;
    preview.hidden = false;
    empty.hidden = true;
    videoMeta.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
    result.hidden = true;
  });

  preview?.addEventListener("loadedmetadata", () => {
    videoDuration = Number(preview.duration || 0);
    const maxDuration = Number(creatorInfo?.max_video_post_duration_sec || 600);
    videoMeta.textContent += ` · ${Math.round(videoDuration)} sec`;
    if (videoDuration > maxDuration) {
      setResult("error", `<strong>Video is too long.</strong><span>This account can post videos up to ${maxDuration} seconds.</span>`);
    }
  });

  form?.querySelectorAll('[name="publish_mode"]').forEach((input) => {
    input.addEventListener("change", updateMode);
  });

  caption?.addEventListener("input", () => {
    captionCount.textContent = String(caption.value.length);
  });

  commercialToggle?.addEventListener("change", updateCommercialState);
  brandOrganic?.addEventListener("change", updateCommercialState);
  brandContent?.addEventListener("change", updateCommercialState);

  document.getElementById("btn-disconnect")?.addEventListener("click", async () => {
    await fetch("/api/content/disconnect", { method: "POST" });
    window.location.reload();
  });

  async function pollStatus(publishId) {
    clearTimeout(statusTimer);
    try {
      const response = await fetch("/api/content/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ publish_id: publishId }),
      });
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "Status unavailable");
      const status = data.status?.status || "PROCESSING";
      const reason = data.status?.fail_reason || "";
      setResult(
        status === "FAILED" ? "error" : "success",
        `<strong>${status.replaceAll("_", " ")}</strong><span>${reason || "TikTok is processing your video. This can take a few minutes."}</span><code>${publishId}</code>`
      );
      if (!["FAILED", "PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"].includes(status)) {
        statusTimer = setTimeout(() => pollStatus(publishId), 5000);
      }
    } catch (error) {
      setResult("error", `<strong>Status check failed</strong><span>${String(error.message || error)}</span>`);
    }
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = fileInput.files?.[0];
    if (!file) {
      setResult("error", "<strong>Select a video first.</strong>");
      return;
    }
    const maxDuration = Number(creatorInfo?.max_video_post_duration_sec || 600);
    if (videoDuration && videoDuration > maxDuration) {
      setResult("error", `<strong>Video is too long.</strong><span>Maximum duration: ${maxDuration} seconds.</span>`);
      return;
    }
    if (!form.reportValidity()) return;

    if (selectedMode() === "direct" && commercialToggle?.checked && !brandOrganic?.checked && !brandContent?.checked) {
      setResult("error", "<strong>Choose a commercial content type.</strong><span>Select Your brand, Branded content, or both.</span>");
      brandOrganic?.focus();
      return;
    }
    if (selectedMode() === "direct" && brandContent?.checked && privacy.value === "SELF_ONLY") {
      setResult("error", "<strong>Choose another privacy setting.</strong><span>Branded content visibility cannot be set to private.</span>");
      privacy.focus();
      return;
    }

    const mode = selectedMode();
    const payload = new FormData();
    payload.set("video", file);
    payload.set("mode", mode);
    payload.set("title", caption.value);
    payload.set("privacy_level", privacy.value);
    ["allow_comment", "allow_duet", "allow_stitch", "commercial_toggle", "brand_content", "brand_organic", "consent"].forEach((name) => {
      payload.set(name, form.querySelector(`[name="${name}"]`)?.checked ? "true" : "false");
    });

    publishButton.disabled = true;
    setResult("working", "<strong>Sending video to TikTok...</strong><span>Keep this page open until the transfer starts.</span>");
    try {
      const response = await fetch("/api/content/upload", { method: "POST", body: payload });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Upload failed");
      setResult(
        "success",
        `<strong>${mode === "draft" ? "Draft transfer started" : "Publish request started"}</strong><span>TikTok may need a few minutes to process and display the video.</span><code>${data.publish_id}</code>`
      );
      pollStatus(data.publish_id);
    } catch (error) {
      setResult("error", `<strong>Could not send the video.</strong><span>${String(error.message || error)}</span>`);
    } finally {
      publishButton.disabled = false;
    }
  });

  updateMode();
  loadCreator();
})();
