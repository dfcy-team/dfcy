(function () {
  const form = document.getElementById("form-export");
  const kindSel = document.getElementById("export-kind");
  const wrapTypes = document.getElementById("wrap-types");
  const wrapFast = document.getElementById("wrap-fast");
  const jobStatus = document.getElementById("job-status");
  const jobLog = document.getElementById("job-log");
  const filesBody = document.getElementById("files-body");
  const fileShopFilter = document.getElementById("file-shop-filter");

  const dayInput = form?.querySelector('input[name="stat_day"]');
  if (dayInput && !dayInput.value) {
    const d = new Date();
    d.setDate(d.getDate() - 2);
    dayInput.value = d.toISOString().slice(0, 10);
  }

  function toggleKindFields() {
    const k = kindSel?.value || "analytics";
    const showAnalytics = k === "analytics";
    if (wrapTypes) wrapTypes.style.display = showAnalytics ? "" : "none";
    if (wrapFast) wrapFast.style.display = showAnalytics ? "" : "none";
  }
  kindSel?.addEventListener("change", toggleKindFields);
  toggleKindFields();

  let pollTimer = null;

  async function pollJob(jobId) {
    const r = await fetch(`/api/jobs/${jobId}`);
    const data = await r.json();
    if (!data.ok) return;
    const job = data.job;
    jobStatus.textContent = `任务 ${job.id} · ${job.kind} · ${job.shop_key} · ${job.stat_day} · 状态：${job.status}`;
    jobLog.textContent = job.log || "";
    jobLog.scrollTop = jobLog.scrollHeight;
    if (job.status === "running" || job.status === "queued") {
      pollTimer = setTimeout(() => pollJob(jobId), 2000);
    } else {
      loadFiles();
    }
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      kind: fd.get("kind"),
      shop_key: fd.get("shop_key"),
      stat_day: fd.get("stat_day"),
      types: fd.get("types") || "all",
      fast_mode: fd.get("fast_mode") === "on",
    };
    jobStatus.textContent = "正在提交任务…";
    jobLog.textContent = "";
    if (pollTimer) clearTimeout(pollTimer);
    try {
      const r = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!data.ok) {
        jobStatus.textContent = "失败：" + data.error;
        return;
      }
      jobStatus.textContent = "任务已创建：" + data.job_id;
      pollJob(data.job_id);
    } catch (err) {
      jobStatus.textContent = String(err);
    }
  });

  function fmtSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  async function loadFiles() {
    const shop = fileShopFilter?.value || "";
    const q = shop ? `?shop=${encodeURIComponent(shop)}` : "";
    filesBody.innerHTML = '<tr><td colspan="4" class="muted">加载中…</td></tr>';
    try {
      const r = await fetch("/api/files" + q);
      const data = await r.json();
      if (!data.ok || !data.files.length) {
        filesBody.innerHTML = '<tr><td colspan="4" class="muted">暂无 Excel 文件</td></tr>';
        return;
      }
      filesBody.innerHTML = data.files
        .map(
          (f) => `<tr>
            <td>${escapeHtml(f.name)}</td>
            <td>${fmtSize(f.size)}</td>
            <td>${escapeHtml(f.mtime)}</td>
            <td><a class="btn" href="/download?path=${encodeURIComponent(f.path)}">下载</a></td>
          </tr>`
        )
        .join("");
    } catch (err) {
      filesBody.innerHTML = `<tr><td colspan="4">${escapeHtml(String(err))}</td></tr>`;
    }
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.getElementById("btn-refresh-files")?.addEventListener("click", loadFiles);
  fileShopFilter?.addEventListener("change", loadFiles);
  loadFiles();
})();
