<template>
  <section class="finance-summary" aria-label="平台账单财务汇总">
    <header v-if="!toolsOnly" class="summary-header">
      <h1>平台账单</h1>
    <details v-if="batch" class="batch-caption">
      <summary>已验收批次 · 设置版本 {{ batch.revision }} · 批次与保存说明</summary>
      <p>{{ batch.label }} · 接入时间 {{ formatTime(batch.imported_at) }} · {{ batch.can_edit ? '调整保存到本地SaaS，保留操作记录' : '当前为只读权限' }}</p>
      <p>店铺口径统一汇总，向上聚合、向下分摊；金额点击查看来源及构成。原HTML2浏览器中另存的个人设置未自动带入。</p>
    </details>
      <el-button :disabled="saving || loading" @click="load">刷新批次</el-button>
    </header>
    <el-alert v-if="batch?.source_changed" title="原始业务数据在接入后有更新；当前仍展示已验收批次，需重新核对并接入新批次。刷新页面不会自动混入未验收数据。" type="warning" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="summary-frame" :aria-busy="loading || saving">
      <div v-if="loading || saving" class="summary-busy" role="status">{{ saving ? '正在校验并保存到本地SaaS…' : '正在加载财务汇总…' }}</div>
      <iframe v-if="document" ref="frame" :srcdoc="document" :style="{ height: frameHeight + 'px' }" :inert="loading || saving" title="财务汇总及流水费用调整" sandbox="allow-scripts allow-popups allow-downloads" @load="loading = false" />
    </div>
  </section>
</template>

<script setup>
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue';
import { fetchFinanceSummary, fetchFinanceSummaryDocument, saveFinanceSummary } from '../../api/financeReconciliation';
const props = defineProps({ initialContext: { type:Object, default:null }, toolsOnly:Boolean });

const batch = ref(null), frame = ref(null), document = ref(''), error = ref(''), loading = ref(false), saving = ref(false);
const frameHeight = ref(600);
const formatTime = value => new Date(value).toLocaleString('zh-CN', { timeZone:'Asia/Shanghai', hour12:false });
let template = '', sourceHash = '', documentVersion = '', requestVersion = 0, alive = true;
let position = null, pendingScroll = null;
const outerScroll = () => frame.value?.closest('.app-main')?.scrollTop || 0;
function show(context) {
  pendingScroll = context?.outerScroll ?? null;
  const bootstrap = JSON.stringify({ dataset:batch.value.dataset, revision:batch.value.revision,
    values:batch.value.values, can_edit:batch.value.can_edit, toolsOnly:props.toolsOnly, viewport_height:window.innerHeight, context }).replace(/</g, '\\u003c');
  loading.value = true;
  document.value = template.replace('__SAAS_FINANCE_BOOTSTRAP__', () => bootstrap);
}
async function load() {
  const version = ++requestVersion;
  loading.value = true; error.value = '';
  try {
    const response = await fetchFinanceSummary();
    if (!alive || version !== requestVersion) return;
    if (!response.success) throw new Error(response.message || '财务批次加载失败');
    const next = response.data;
    if (document.value && batch.value?.dataset === next.dataset && batch.value?.revision === next.revision && batch.value?.can_edit === next.can_edit && sourceHash === next.source_hash && documentVersion === next.document_version) {
      batch.value = next; loading.value = false; return;
    }
    if (sourceHash !== next.source_hash || documentVersion !== next.document_version || !template) {
      const result = await fetchFinanceSummaryDocument(next.dataset);
      if (!alive || version !== requestVersion) return;
      if (!result.success) throw new Error(result.message || '财务页面加载失败');
      template = await result.blob.text();
      if (!template.includes('__SAAS_FINANCE_BOOTSTRAP__')) throw new Error('财务页面版本异常，请重新接入已验收批次');
      sourceHash = next.source_hash;
      documentVersion = next.document_version;
    }
    if (!alive || version !== requestVersion) return;
    const context = position ? { ...position, outerScroll:outerScroll() } : props.initialContext || undefined;
    batch.value = next; show(context);
  } catch (reason) {
    if (alive && version === requestVersion) { document.value = ''; batch.value = null; loading.value = false; error.value = reason?.message || '财务汇总加载失败'; }
  }
}
async function onMessage(event) {
  const message = event.data;
  if (event.source !== frame.value?.contentWindow || !message || !batch.value) return;
  if (message.dataset !== batch.value.dataset || message.revision !== batch.value.revision) return;
  if (message.type === 'finance-summary-size') {
    if (Number.isFinite(message.height) && message.height > 0) frameHeight.value = Math.ceil(message.height);
    nextTick(onResize);
    if (pendingScroll != null) { const top=pendingScroll; pendingScroll=null; nextTick(()=>{ const main=frame.value?.closest('.app-main'); if(main)main.scrollTop=top; }); }
    return;
  }
  if (message.type === 'finance-summary-context') { position = message.context; return; }
  if (message.type !== 'finance-summary-write' || saving.value) return;
  saving.value = true; error.value = '';
  try {
    const response = await saveFinanceSummary(batch.value.dataset, { revision:message.revision, key:message.key, value:message.value, reason:message.reason });
    if (!alive) return;
    if (!response.success) throw new Error(response.message || '保存未完成，请刷新核对');
    Object.assign(batch.value, response.data); show({ ...message.context, outerScroll:outerScroll() });
  } catch (reason) {
    if (!alive) return;
    // Re-read authoritative state after a conflict or an uncertain network result.
    const response = await fetchFinanceSummary().catch(() => null);
    if (response?.success && response.data.source_hash === sourceHash) { batch.value = response.data; show({ ...message.context, outerScroll:outerScroll() }); }
    else { document.value = ''; loading.value = false; }
    error.value = (reason?.message || '保存结果未确认') + '；请核对当前版本和操作记录后再修改。';
  } finally { if (alive) saving.value = false; }
}
function onResize() {
  const el=frame.value;if(!el)return;
  const rect=el.getBoundingClientRect(),mainTop=el.closest('.app-main')?.getBoundingClientRect().top||0;
  el.contentWindow?.postMessage({ type:'finance-summary-viewport', dataset:batch.value?.dataset, height:window.innerHeight, top:Math.max(0,mainTop-rect.top), visible:Math.max(160,window.innerHeight-Math.max(mainTop,rect.top)-16) }, '*');
}
onMounted(() => { window.addEventListener('message', onMessage); window.addEventListener('resize', onResize); window.addEventListener('scroll', onResize, true); load(); });
onBeforeUnmount(() => { alive = false; requestVersion++; window.removeEventListener('message', onMessage); window.removeEventListener('resize', onResize); window.removeEventListener('scroll', onResize, true); });
</script>

<style scoped>
.finance-summary{display:grid;gap:8px;min-width:0}
.summary-header{display:flex;justify-content:space-between;align-items:center;gap:16px}
.summary-header h1{margin:0;font-size:20px;color:#172033}
.batch-caption{margin:0;font-size:12px;color:#526176;line-height:1.7}
.summary-header .batch-caption{flex:1;min-width:0}
.batch-caption summary{cursor:pointer}
.batch-caption p{margin:5px 0}
.summary-frame{position:relative;min-height:160px}
.summary-frame iframe{display:block;width:100%;border:0;background:#f5f7fb}
.summary-busy{position:absolute;inset:0;z-index:1;display:grid;place-items:center;background:rgba(245,247,251,.96);color:#253c60;font-size:14px}
@media(max-width:700px){.summary-header{align-items:flex-start;flex-wrap:wrap}.summary-header .batch-caption{order:3;flex-basis:100%}.batch-caption{overflow-wrap:anywhere}}
</style>
