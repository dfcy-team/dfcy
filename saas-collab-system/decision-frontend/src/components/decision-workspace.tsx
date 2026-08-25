"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { apiRequest, can, clearSession, CurrentUser, fetchCurrentUser } from "../lib/auth-api";

type Row = Record<string, unknown>;
type ListData = { count?: number; results?: Row[]; summary?: Array<{ label: string; value: unknown }> };
type View = {
  path: string; title: string; description: string; permission: string; endpoint: string; empty: string;
  columns: Array<[string, string]>;
};

const APP_BASE = "/decision-app";
const HOST_BASE = "/decision";
const views: View[] = [
  { path: "/inventory/alerts", title: "库存预警", description: "按真实库存快照与近 30 天销量识别库存风险。", permission: "alerts.view", endpoint: "/api/internal/alerts/inventory/", empty: "暂无库存预警", columns: [["sku_code", "SKU"], ["product_name", "商品"], ["alert_type", "预警类型"], ["severity", "风险"], ["available_stock", "可用库存"], ["coverage_days", "覆盖天数"], ["status", "状态"], ["triggered_at", "触发时间"]] },
  { path: "/inventory/replenishment", title: "补货建议", description: "按安全库存、供应提前期和补货周期复核建议数量。", permission: "replenishment.view", endpoint: "/api/internal/replenishment/recommendations/", empty: "暂无补货建议", columns: [["sku_code", "SKU"], ["product_name", "商品"], ["suggested_quantity", "建议数量"], ["suggested_date", "建议下单日"], ["confidence", "置信度"], ["status", "复核状态"], ["created_at", "生成时间"]] },
  { path: "/lifecycle/reviews", title: "生命周期复盘", description: "结合销量、退款和库存证据形成人工复盘建议。", permission: "products.lifecycle.view", endpoint: "/api/internal/lifecycle/reviews/", empty: "暂无待复盘商品", columns: [["spu_code", "SPU"], ["product_name", "商品"], ["current_stage", "当前阶段"], ["recommended_stage", "建议阶段"], ["confidence", "置信度"], ["status", "复核状态"], ["review_period_end", "口径截止"]] },
  { path: "/lifecycle/history", title: "复盘历史", description: "只读查看人工确认或驳回的阶段、理由和操作者。", permission: "products.lifecycle.view", endpoint: "/api/internal/lifecycle/decisions/", empty: "暂无复盘历史", columns: [["spu_code", "SPU"], ["product_name", "商品"], ["decision", "人工结论"], ["from_stage", "原阶段"], ["to_stage", "结果阶段"], ["actor_name", "复核人"], ["created_at", "复核时间"]] },
  { path: "/lifecycle/clearance-requests", title: "清仓申请", description: "汇总生命周期复盘发起的清仓审批，不执行降价或下架。", permission: "workflow.approvals.view", endpoint: "/api/internal/workflow/approvals/?approval_type=clearance", empty: "暂无清仓申请", columns: [["title", "申请"], ["business_id", "复盘记录"], ["status", "审批状态"], ["requested_by_name", "申请人"], ["reviewed_by_name", "审批人"], ["created_at", "申请时间"]] },
  { path: "/alerts/business", title: "经营预警", description: "集中呈现授权、同步、映射和数据质量等跨模块异常。", permission: "alerts.view", endpoint: "/api/internal/alerts/business/", empty: "暂无经营预警", columns: [["title", "预警"], ["business_type", "对象类型"], ["severity", "风险"], ["metric_value", "指标值"], ["threshold_value", "阈值"], ["status", "状态"], ["triggered_at", "触发时间"]] },
];

const labels: Record<string, string> = {
  open: "待处理", assigned: "已分派", in_progress: "处理中", silenced: "已静默", closed: "已关闭",
  suggested: "待复核", accepted: "已接受", rejected: "已驳回", expired: "已过期", confirmed: "已确认",
  pending: "待审批", approved: "已通过", high: "高", medium: "中", low: "低", healthy: "正常",
  stockout_risk: "缺货风险", low_coverage: "低覆盖", overstock_risk: "积压风险", slow_moving: "滞销",
};

function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return labels[String(value)] || String(value);
}

function dateValue(value: unknown) {
  if (!value) return "—";
  const parsed = new Date(String(value));
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString("zh-CN", { hour12: false }) : display(value);
}

function cell(key: string, value: unknown) {
  if (key.endsWith("_at") || key.endsWith("_date") || key === "review_period_end") return dateValue(value);
  if (key === "confidence") return `${Math.round(Number(value || 0) * 100)}%`;
  return display(value);
}

function endpointWithQuery(view: View, query: { search: string; status: string; severity: string }, page: number) {
  const [path, original = ""] = view.endpoint.split("?");
  const params = new URLSearchParams(original);
  params.set("page", String(page));
  params.set("page_size", "30");
  if (query.status) params.set("status", query.status);
  if (query.severity) params.set("severity", query.severity);
  if (query.search) params.set("search", query.search);
  return `${path}?${params}`;
}

export function DecisionWorkspace({ embedded = false }: { embedded?: boolean }) {
  const pathname = usePathname().replace(/^\/decision-app/, "") || "/inventory/alerts";
  const view = views.find((item) => item.path === pathname) || views[0];
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState({ search: "", status: "", severity: "" });
  const [query, setQuery] = useState(draft);
  const [selected, setSelected] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const redirectToLogin = useCallback(() => {
    const target = `/login?redirect=${encodeURIComponent(`${HOST_BASE}${view.path}`)}`;
    if (window.parent !== window) window.parent.location.assign(target);
    else window.location.assign(target);
  }, [view.path]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const me = await fetchCurrentUser();
      setUser(me.data);
      if (me.data.user_type !== "internal" || !can(me.data, view.permission)) {
        setRows([]); setTotal(0); setError("当前角色无权访问该经营决策页面。"); return;
      }
      const response = await apiRequest<ListData>(endpointWithQuery(view, query, page));
      setRows(response.data?.results || []);
      setTotal(Number(response.data?.count || 0));
    } catch (cause) {
      if (cause instanceof Error && cause.message === "AUTH_REQUIRED") return redirectToLogin();
      setRows([]); setTotal(0); setError(cause instanceof Error ? cause.message : "经营决策数据读取失败");
    } finally { setLoading(false); }
  }, [page, query, redirectToLogin, view]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setPage(1); setSelected(null); }, [view.path]);

  const summary = useMemo(() => [
    ["当前结果", total], ["数据边界", `租户 ${user?.tenant_id || "—"}`],
  ], [total, user]);

  function submit(event: FormEvent) { event.preventDefault(); setPage(1); setQuery({ ...draft }); }
  function logout() {
    clearSession();
    if (window.parent !== window) window.parent.location.assign("/login");
    else window.location.assign("/login");
  }

  return <div className={`app-shell${embedded ? " embedded" : ""}`}>
    {!embedded ? <aside className="sidebar">
      <a className="brand" href="/"><strong>SaaS 协同系统</strong><span>经营决策 · Next.js</span></a>
      <nav><a href="/">← 返回主系统</a><p>经营决策</p>{views.map((item) => can(user, item.permission) ? <a key={item.path} className={item.path === view.path ? "active" : ""} href={`${APP_BASE}${item.path}`}>{item.title}</a> : null)}</nav>
    </aside> : null}
    <section className="workspace">
      {!embedded ? <header className="topbar"><div><span>工作台</span><b>/</b><strong>{view.title}</strong></div><div className="identity"><span>Pilot API</span><p><strong>{user?.username || "身份校验中"}</strong><small>租户 {user?.tenant_id || "—"} · RBAC 已接入</small></p><button onClick={logout}>退出</button></div></header> : null}
      <main>
        <header className="page-head"><div><p>经营决策</p><h1>{view.title}</h1><span>{view.description}</span></div><button className="secondary" onClick={() => void load()} disabled={loading}>{loading ? "检查中…" : "重新检查数据"}</button></header>
        <div className="boundary"><strong>辅助决策边界</strong><span>不会自动采购、改价、上下架或触发 RPA；读取和处理范围由 Django tenant、RBAC 与 data_scope 最终校验。</span></div>
        {error ? <div className="error" role="alert">{error}</div> : null}
        <section className="summary">{summary.map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</section>
        <form className="filters" onSubmit={submit}><label><span>商品或业务对象</span><input value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="输入 SKU、SPU 或名称" /></label><label><span>状态</span><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">全部状态</option>{["open", "silenced", "closed", "suggested", "accepted", "rejected", "confirmed", "pending", "approved"].map((value) => <option key={value} value={value}>{display(value)}</option>)}</select></label>{view.path.includes("alerts") ? <label><span>风险等级</span><select value={draft.severity} onChange={(event) => setDraft({ ...draft, severity: event.target.value })}><option value="">全部风险</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label> : null}<div><button type="submit">查询</button><button type="button" className="secondary" onClick={() => { const reset = { search: "", status: "", severity: "" }; setDraft(reset); setQuery(reset); setPage(1); }}>重置</button></div></form>
        <section className="table-panel" aria-busy={loading}><header><div><h2>{view.title}清单</h2><p>点击记录核对计算证据与来源口径。</p></div><strong>{total} 条</strong></header>{loading ? <div className="empty">正在读取当前权限范围内的数据…</div> : rows.length ? <><div className="table-scroll"><table><thead><tr>{view.columns.map(([, label]) => <th key={label}>{label}</th>)}<th>操作</th></tr></thead><tbody>{rows.map((row) => <tr key={String(row.id)}>{view.columns.map(([key]) => <td key={key}>{cell(key, row[key])}</td>)}<td><button className="link" onClick={() => setSelected(row)}>查看证据</button></td></tr>)}</tbody></table></div><footer><span>第 {page} 页</span><div><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={page * 30 >= total} onClick={() => setPage(page + 1)}>下一页</button></div></footer></> : <div className="empty"><strong>{view.empty}</strong><p>先检查 API 接入、同步运行、SKU 映射与事实数据范围。</p></div>}</section>
      </main>
    </section>
    {selected ? <div className="drawer-layer"><button className="backdrop" aria-label="关闭" onClick={() => setSelected(null)}/><aside className="drawer" role="dialog" aria-modal="true"><header><div><h2>证据与审计信息</h2><p>记录 #{String(selected.id)}</p></div><button onClick={() => setSelected(null)}>关闭</button></header><dl>{Object.entries(selected).slice(0, 18).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{display(value)}</dd></div>)}</dl><section><h3>来源证据</h3><pre>{JSON.stringify(selected.source_summary || selected.source_metrics || selected.detail || {}, null, 2)}</pre></section></aside></div> : null}
  </div>;
}
