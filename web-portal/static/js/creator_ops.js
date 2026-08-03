const state = {
  tasks: [],
  creators: [],
  taskPage: 1,
  taskPageSize: 20,
  samplePage: 1,
  samplePageSize: 50,
  sampleTokens: { 1: "" },
  selectedTaskId: "",
  samplesLoaded: false,
};

const viewTitles = {
  tasks: ["BD 工作台", "建联任务"],
  samples: ["履约管理", "送样履约"],
  videos: ["数据回收", "视频结果"],
  creators: ["BD 工作台", "达人协作"],
};

const resultLabels = {
  pending: "待联系",
  success: "建联成功",
  rejected: "拒绝",
  no_response: "无回复",
  blocked: "拉黑",
};

const stageLabels = {
  none: "未送样",
  pending_sample: "待发样",
  shipped: "已发货",
  signed: "已签收",
  creating: "创作中",
  published: "已发布",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function icons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatInt(value) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(Number(value || 0));
}

function formatMoney(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Number(value || 0));
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
  if (!response.ok || payload.ok === false) throw new Error(payload.error || "请求失败");
  return payload;
}

function statusClass(status) {
  if (["已完成", "已发布"].includes(status)) return "complete";
  if (["进行中", "建联成功"].includes(status)) return "active";
  if (["待处理", "待发样", "已发货", "已签收", "创作中"].includes(status)) return "wait";
  if (["已关闭", "已取消", "拒绝", "拉黑"].includes(status)) return "fail";
  return "neutral";
}

function updateShopOptions() {
  const shops = [...new Set(state.tasks.map((task) => task.shop).filter(Boolean))].sort();
  ["task-shop", "sample-shop", "video-shop"].forEach((id) => {
    const select = $(`#${id}`);
    const first = select.options[0]?.outerHTML || '<option value="">全部店铺</option>';
    select.innerHTML = first + shops.map((shop) => `<option value="${escapeHtml(shop)}">${escapeHtml(shop)}</option>`).join("");
  });
}

function filteredTasks() {
  const query = $("#task-search").value.trim().toLowerCase();
  const status = $("#task-status").value;
  const shop = $("#task-shop").value;
  return state.tasks.filter((task) => {
    const haystack = [task.id, task.name, task.shop, task.product_id, task.sku_prefix, task.owner].join(" ").toLowerCase();
    return (!query || haystack.includes(query)) && (!status || task.status === status) && (!shop || task.shop === shop);
  });
}

function renderTasks() {
  const rows = filteredTasks();
  const pages = Math.max(1, Math.ceil(rows.length / state.taskPageSize));
  state.taskPage = Math.min(Math.max(1, state.taskPage), pages);
  const offset = (state.taskPage - 1) * state.taskPageSize;
  const items = rows.slice(offset, offset + state.taskPageSize);
  $("#task-total").textContent = `${formatInt(rows.length)} 个任务`;
  $("#task-page").textContent = `${state.taskPage} / ${pages}`;
  $("#task-prev").disabled = state.taskPage <= 1;
  $("#task-next").disabled = state.taskPage >= pages;
  $("#task-body").innerHTML = items.length
    ? items.map((task) => {
        const target = Math.max(Number(task.target_count || 0), 1);
        const progress = Math.min(100, Math.round((Number(task.linked_count || 0) / target) * 100));
        const avatar = task.owner_avatar
          ? `<img src="${escapeHtml(task.owner_avatar)}" alt=""/>`
          : `<span class="owner-letter">${escapeHtml((task.owner || "BD").slice(0, 1))}</span>`;
        return `<tr data-task-id="${escapeHtml(task.id)}">
          <td><div class="task-name"><strong>${escapeHtml(task.name)}</strong><span class="task-id">${escapeHtml(task.id)} · ${escapeHtml(task.source)}</span></div></td>
          <td><div class="cell-stack"><strong>${escapeHtml(task.shop || "-")}</strong><span>${escapeHtml(task.product_id || task.sku_prefix || "未关联商品")}</span></div></td>
          <td><span class="priority ${escapeHtml((task.priority || "T2").toLowerCase())}">${escapeHtml(task.priority || "T2")}</span></td>
          <td><div class="progress-cell"><div class="progress-label"><span>${formatInt(task.linked_count)} / ${formatInt(task.target_count)}</span><b>${progress}%</b></div><div class="progress-track"><i style="width:${progress}%"></i></div></div></td>
          <td><div class="owner">${avatar}<span>${escapeHtml(task.owner || "BD")}</span></div></td>
          <td><span class="status ${statusClass(task.status)}">${escapeHtml(task.status)}</span></td>
          <td>${escapeHtml(task.dispatch_date || task.start_date || "-")}</td>
          <td><button class="open-task" title="打开任务" data-open-task="${escapeHtml(task.id)}"><i data-lucide="arrow-up-right"></i></button></td>
        </tr>`;
      }).join("")
    : '<tr><td colspan="8" class="empty-cell">没有符合条件的任务</td></tr>';
  $$('[data-open-task]').forEach((button) => button.addEventListener("click", () => openTask(button.dataset.openTask)));
  icons();
}

function renderCreators() {
  const query = $("#creator-search").value.trim().toLowerCase();
  const rows = state.creators.filter((item) => !query || [item.handle, item.task_name, item.shop].join(" ").toLowerCase().includes(query));
  $("#creator-body").innerHTML = rows.length
    ? rows.map((item) => `<tr>
        <td><div class="cell-stack"><strong>@${escapeHtml(item.handle)}</strong><span>${escapeHtml(item.creator_id || "未填数字ID")}</span></div></td>
        <td><div class="cell-stack"><strong>${escapeHtml(item.task_name)}</strong><span>${escapeHtml(item.task_id)}</span></div></td>
        <td>${escapeHtml(item.shop)}</td>
        <td><span class="status ${statusClass(resultLabels[item.outreach_result])}">${escapeHtml(resultLabels[item.outreach_result] || item.outreach_result)}</span></td>
        <td><span class="status ${statusClass(stageLabels[item.sample_status])}">${escapeHtml(stageLabels[item.sample_status] || item.sample_status)}</span></td>
        <td>${escapeHtml((item.updated_at || "").slice(0, 16))}</td>
        <td><button class="open-task" title="查询视频" data-creator-video="${escapeHtml(item.id)}"><i data-lucide="play"></i></button></td>
      </tr>`).join("")
    : '<tr><td colspan="7" class="empty-cell">网站中还没有BD跟进记录</td></tr>';
  $$('[data-creator-video]').forEach((button) => button.addEventListener("click", () => {
    const item = state.creators.find((creator) => String(creator.id) === button.dataset.creatorVideo);
    if (!item) return;
    switchView("videos");
    $("#video-shop").value = item.shop;
    $("#video-handle").value = item.handle;
    searchVideos();
  }));
  icons();
}

function setMetrics(payload) {
  $("#metric-tasks").textContent = formatInt(payload.stats.tasks);
  $("#metric-active").textContent = formatInt(payload.stats.active_tasks);
  $("#metric-linked").textContent = formatInt(payload.stats.linked);
  $("#metric-samples").textContent = formatInt(payload.stats.samples);
  $("#metric-video-date").textContent = payload.latest_video_date || "-";
  $("#nav-task-count").textContent = formatInt(payload.stats.active_tasks);
  $("#sync-time").textContent = `同步于 ${payload.synced_at}`;
}

async function loadBootstrap(showMessage = false) {
  $("#refresh-all svg")?.classList.add("spinning");
  try {
    const payload = await api("/api/creator-ops/bootstrap");
    state.tasks = payload.tasks;
    state.creators = payload.creators;
    setMetrics(payload);
    updateShopOptions();
    renderTasks();
    renderCreators();
    if (showMessage) toast("飞书与视频库数据已刷新");
  } catch (error) {
    $("#task-body").innerHTML = `<tr><td colspan="8" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
    toast(error.message, true);
  } finally {
    $("#refresh-all svg")?.classList.remove("spinning");
    icons();
  }
}

function switchView(name) {
  $$(".view").forEach((node) => node.classList.toggle("is-active", node.id === `view-${name}`));
  $$(".nav-item").forEach((node) => node.classList.toggle("is-active", node.dataset.view === name));
  $("#page-eyebrow").textContent = viewTitles[name][0];
  $("#page-title").textContent = viewTitles[name][1];
  $("#sidebar").classList.remove("is-open");
  if (name === "samples" && !state.samplesLoaded) loadSamples();
}

function creatorCard(item) {
  const canSample = item.outreach_result === "success";
  const resultOptions = Object.entries(resultLabels).map(([value, label]) => `<option value="${value}" ${item.outreach_result === value ? "selected" : ""}>${label}</option>`).join("");
  const stageOptions = Object.entries(stageLabels).map(([value, label]) => `<option value="${value}" ${item.sample_status === value ? "selected" : ""}>${label}</option>`).join("");
  return `<div class="creator-item" data-local-creator="${item.id}">
    <div class="creator-item-head"><div class="creator-handle"><b>@</b><div><strong>${escapeHtml(item.handle)}</strong><small>${escapeHtml(item.creator_id || "未填数字ID")}</small></div></div><button class="open-task" data-video-handle="${escapeHtml(item.handle)}" title="查询视频"><i data-lucide="chart-no-axes-combined"></i></button></div>
    <div class="creator-controls">
      <select data-result-id="${item.id}" aria-label="建联结果">${resultOptions}</select>
      <select data-stage-id="${item.id}" aria-label="履约阶段" ${canSample ? "" : "disabled"}>${stageOptions}</select>
    </div>
  </div>`;
}

async function openTask(taskId) {
  state.selectedTaskId = taskId;
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;
  $("#drawer-source").textContent = task.source;
  $("#drawer-title").textContent = task.name;
  $("#drawer-id").textContent = `${task.id} · ${task.shop || "未填店铺"}`;
  $("#task-facts").innerHTML = [
    ["目标商品", task.product_id || task.sku_prefix || "-"],
    ["目标达人", `${formatInt(task.target_count)} 人`],
    ["负责人", task.owner || "BD"],
    ["任务状态", task.status || "进行中"],
  ].map(([label, value]) => `<div><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  $("#drawer-creators").innerHTML = '<div class="loading-row"><span></span>正在读取任务记录</div>';
  $("#drawer-samples").innerHTML = '<div class="loading-row"><span></span>正在匹配送样记录</div>';
  $("#task-drawer").classList.add("is-open");
  $("#task-drawer").setAttribute("aria-hidden", "false");
  $("#drawer-mask").classList.add("is-open");
  try {
    const payload = await api(`/api/creator-ops/tasks/${encodeURIComponent(taskId)}`);
    $("#drawer-creator-count").textContent = `${payload.creators.length} 人`;
    $("#drawer-creators").innerHTML = payload.creators.length ? payload.creators.map(creatorCard).join("") : '<div class="empty-box">尚未添加BD跟进达人</div>';
    $("#drawer-sample-count").textContent = `${payload.samples.length} 条`;
    $("#drawer-samples").innerHTML = payload.samples.length
      ? payload.samples.slice(0, 30).map((sample) => `<div class="sample-item"><div><strong>@${escapeHtml(sample.handle || "未知达人")}</strong><span>${escapeHtml(sample.product || sample.sku || "未填产品")} · ${escapeHtml(sample.order_no || "无样品订单")}</span></div><span class="status ${statusClass(sample.status)}">${escapeHtml(sample.status)}</span></div>`).join("")
      : '<div class="empty-box">当前任务ID未匹配到飞书送样记录</div>';
    bindCreatorControls(payload.creators);
    icons();
  } catch (error) {
    $("#drawer-creators").innerHTML = `<div class="empty-box">${escapeHtml(error.message)}</div>`;
    $("#drawer-samples").innerHTML = "";
  }
}

function closeDrawer() {
  $("#task-drawer").classList.remove("is-open");
  $("#task-drawer").setAttribute("aria-hidden", "true");
  $("#drawer-mask").classList.remove("is-open");
}

function bindCreatorControls(creators) {
  $$('[data-result-id]').forEach((select) => select.addEventListener("change", async () => {
    try {
      await api(`/api/creator-ops/creators/${select.dataset.resultId}`, { method: "PATCH", body: JSON.stringify({ outreach_result: select.value, ...(select.value === "success" ? {} : { sample_status: "none" }) }) });
      toast(select.value === "success" ? "已标记建联成功，可以进入送样" : "建联结果已更新");
      await loadBootstrap();
      await openTask(state.selectedTaskId);
    } catch (error) { toast(error.message, true); }
  }));
  $$('[data-stage-id]').forEach((select) => select.addEventListener("change", async () => {
    try {
      await api(`/api/creator-ops/creators/${select.dataset.stageId}`, { method: "PATCH", body: JSON.stringify({ sample_status: select.value }) });
      toast(`履约状态已更新为${stageLabels[select.value]}`);
      await loadBootstrap();
      await openTask(state.selectedTaskId);
    } catch (error) { toast(error.message, true); }
  }));
  $$('[data-video-handle]').forEach((button) => button.addEventListener("click", () => {
    const task = state.tasks.find((item) => item.id === state.selectedTaskId);
    closeDrawer();
    switchView("videos");
    $("#video-shop").value = task?.shop || "";
    $("#video-handle").value = button.dataset.videoHandle;
    searchVideos();
  }));
}

async function loadSamples() {
  $("#sample-body").innerHTML = '<tr><td colspan="8"><div class="loading-row"><span></span>正在读取飞书送样信息表</div></td></tr>';
  const params = new URLSearchParams({
    page: state.samplePage,
    page_size: state.samplePageSize,
    q: $("#sample-search").value.trim(),
    shop: $("#sample-shop").value,
    status: $("#sample-status").value,
    page_token: state.sampleTokens[state.samplePage] || "",
  });
  try {
    const payload = await api(`/api/creator-ops/samples?${params}`);
    state.samplesLoaded = true;
    const pages = Math.max(1, Math.ceil(payload.total / payload.page_size));
    $("#sample-total").textContent = `${formatInt(payload.total)} 条记录`;
    $("#sample-page").textContent = `${payload.page} / ${pages}`;
    $("#sample-prev").disabled = payload.page <= 1;
    $("#sample-next").disabled = !payload.has_more;
    if (payload.next_page_token) state.sampleTokens[payload.page + 1] = payload.next_page_token;
    $("#sample-body").innerHTML = payload.items.length
      ? payload.items.map((item) => `<tr><td><span class="task-id">${escapeHtml(item.id)}</span></td><td><div class="cell-stack"><strong>@${escapeHtml(item.handle || "未知")}</strong><span>${escapeHtml(item.creator_id || "未找到ID")}</span></div></td><td>${escapeHtml(item.shop)}</td><td><div class="cell-stack"><strong>${escapeHtml(item.product || "-")}</strong><span>${escapeHtml(item.sku || item.product_id || "-")}</span></div></td><td>${escapeHtml(item.order_no || "-")}</td><td>${formatMoney(item.cost)}</td><td><span class="status ${statusClass(item.status)}">${escapeHtml(item.status)}</span></td><td>${escapeHtml(item.date || "-")}</td></tr>`).join("")
      : '<tr><td colspan="8" class="empty-cell">没有符合条件的送样记录</td></tr>';
  } catch (error) {
    $("#sample-body").innerHTML = `<tr><td colspan="8" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
    toast(error.message, true);
  }
}

async function searchVideos() {
  const shop = $("#video-shop").value;
  const handle = $("#video-handle").value.trim().replace(/^@/, "");
  if (!shop || !handle) return toast("请选择店铺并填写达人账号", true);
  $("#video-empty").classList.remove("hidden");
  $("#video-empty").innerHTML = '<div class="loading-row"><span></span>正在匹配视频数据库</div>';
  $("#video-result").classList.add("hidden");
  try {
    const payload = await api(`/api/creator-ops/videos?shop=${encodeURIComponent(shop)}&handle=${encodeURIComponent(handle)}`);
    const summary = payload.summary || {};
    $("#video-count").textContent = formatInt(summary.videos);
    $("#video-vv").textContent = formatInt(summary.vv);
    $("#video-orders").textContent = formatInt(summary.orders);
    $("#video-items").textContent = formatInt(summary.items_sold);
    $("#video-gmv").textContent = formatMoney(summary.gmv);
    $("#video-body").innerHTML = payload.videos.length
      ? payload.videos.map((video) => `<tr><td><span class="task-id">${escapeHtml(video.video_id)}</span></td><td><div class="cell-stack"><strong>${escapeHtml(video.title)}</strong></div></td><td><span title="${escapeHtml(video.product)}">${escapeHtml((video.product || "-").slice(0, 30))}</span></td><td>${escapeHtml((video.publish_time || "-").slice(0, 16))}</td><td>${formatInt(video.vv)}</td><td>${formatInt(video.orders)}</td><td>${formatInt(video.items_sold)}</td><td>${formatMoney(video.gmv)}</td></tr>`).join("")
      : '<tr><td colspan="8" class="empty-cell">最近30天未匹配到该达人在此店铺的视频</td></tr>';
    $("#video-empty").classList.add("hidden");
    $("#video-result").classList.remove("hidden");
  } catch (error) {
    $("#video-empty").innerHTML = `<i data-lucide="circle-alert"></i><strong>${escapeHtml(error.message)}</strong>`;
    toast(error.message, true);
    icons();
  }
}

async function submitTask(event) {
  event.preventDefault();
  const form = $("#task-form");
  if (!form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  try {
    const payload = await api("/api/creator-ops/tasks", { method: "POST", body: JSON.stringify(data) });
    $("#task-modal").close();
    form.reset();
    toast("建联任务已创建并分配给BD");
    await loadBootstrap();
    openTask(payload.task_id);
  } catch (error) { toast(error.message, true); }
}

async function submitCreator(event) {
  event.preventDefault();
  const form = $("#creator-form");
  if (!form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  try {
    await api(`/api/creator-ops/tasks/${encodeURIComponent(state.selectedTaskId)}/creators`, { method: "POST", body: JSON.stringify(data) });
    $("#creator-modal").close();
    form.reset();
    toast(data.outreach_result === "success" ? "达人已添加并标记建联成功" : "达人已加入任务");
    await loadBootstrap();
    await openTask(state.selectedTaskId);
  } catch (error) { toast(error.message, true); }
}

function debounce(fn, delay = 350) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#mobile-menu").addEventListener("click", () => $("#sidebar").classList.toggle("is-open"));
  $("#refresh-all").addEventListener("click", () => loadBootstrap(true));
  $("#task-search").addEventListener("input", () => { state.taskPage = 1; renderTasks(); });
  $("#task-status").addEventListener("change", () => { state.taskPage = 1; renderTasks(); });
  $("#task-shop").addEventListener("change", () => { state.taskPage = 1; renderTasks(); });
  $("#task-prev").addEventListener("click", () => { state.taskPage -= 1; renderTasks(); });
  $("#task-next").addEventListener("click", () => { state.taskPage += 1; renderTasks(); });
  $("#new-task").addEventListener("click", () => $("#task-modal").showModal());
  $("#task-submit").addEventListener("click", submitTask);
  $("#add-creator").addEventListener("click", () => $("#creator-modal").showModal());
  $("#creator-submit").addEventListener("click", submitCreator);
  $("#close-drawer").addEventListener("click", closeDrawer);
  $("#drawer-mask").addEventListener("click", closeDrawer);
  $("#sample-refresh").addEventListener("click", () => loadSamples());
  $("#sample-search").addEventListener("input", debounce(() => { state.samplePage = 1; state.sampleTokens = { 1: "" }; loadSamples(); }));
  $("#sample-shop").addEventListener("change", () => { state.samplePage = 1; state.sampleTokens = { 1: "" }; loadSamples(); });
  $("#sample-status").addEventListener("change", () => { state.samplePage = 1; state.sampleTokens = { 1: "" }; loadSamples(); });
  $("#sample-prev").addEventListener("click", () => { state.samplePage -= 1; loadSamples(); });
  $("#sample-next").addEventListener("click", () => { state.samplePage += 1; loadSamples(); });
  $("#video-search").addEventListener("click", searchVideos);
  $("#video-handle").addEventListener("keydown", (event) => { if (event.key === "Enter") searchVideos(); });
  $("#creator-search").addEventListener("input", renderCreators);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
}

bindEvents();
icons();
loadBootstrap();
