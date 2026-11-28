<template>
  <div v-if="entryEnabled && !open && !blocked" ref="floatElement" class="tracking-float" :style="{right: `${right}px`, bottom: `${bottom}px`}" data-html2canvas-ignore @pointerdown="start" @pointerup="stop" @pointermove="move" @pointercancel="cancel" @lostpointercapture="stop">
    <el-button type="primary" round @click="show">{{collapsed ? '跟踪' : '事件跟踪'}}</el-button>
    <el-button class="collapse-button" text :aria-label="collapsed ? '展开事件跟踪入口' : '收起事件跟踪入口'" @click.stop="collapsed = !collapsed">{{collapsed ? '+' : '−'}}</el-button>
  </div>
  <el-drawer v-model="open" class="tracking-capture-drawer" title="发起页面跟踪" size="min(760px, 96vw)" append-to-body>
    <el-alert v-if="candidateError" :title="candidateError" type="error" :closable="false" show-icon />
    <el-button v-if="candidateError" :loading="loadingCandidates" @click="loadCandidates">重新加载办理人</el-button>
    <p v-if="loadingCandidates">正在加载可选办理人…</p>
    <CaptureFlow v-if="open" :context="flowContext" :candidates="candidates" :can-continue="candidatesReady" :screenshot-enabled="rule?.screenshot_enabled !== false" @created="created" />
  </el-drawer>
</template>
<script setup>
import {computed, ref, watch, onMounted, onBeforeUnmount} from 'vue';
import {useRoute} from 'vue-router';
import {tracking} from '../../api/issueTracking';
import CaptureFlow from './CaptureFlow.vue';
const route = useRoute();
const open = ref(false), collapsed = ref(false), right = ref(48), bottom = ref(Math.max(160, Math.round(innerHeight / 2))), rules = ref([]), blocked = ref(false), floatElement = ref(null);
const candidates = ref({users: [], departments: []}), candidateError = ref(''), candidatesReady = ref(false), loadingCandidates = ref(false), flowContext = ref({});
const record = ref(null);
let origin = null, dragged = false, observer, candidateRequest = 0, routeRequest = 0, alive = true;
const context = computed(() => {
  const match = route.path.match(/^\/workflow\/(approvals|exceptions)\/(\d+)$/);
  return {menu_key: match ? `/workflow/${match[1]}` : route.path, page_path: route.path, ...(match ? {record_type: match[1] === 'approvals' ? 'approval' : 'exception', record_id: match[2]} : record.value || {})};
});
const rule = computed(() => rules.value.find(item => item.menu_key === context.value.menu_key));
const entryEnabled = computed(() => rule.value?.enabled && (rule.value.scope !== 'record' || context.value.record_id) && (rule.value.scope !== 'page' || !context.value.record_id));
function receive(event) { record.value = event.detail; }
function clamp() {
  const width = floatElement.value?.offsetWidth || 150, height = floatElement.value?.offsetHeight || 40;
  right.value = Math.max(24, Math.min(Math.max(24, innerWidth - width - 8), right.value));
  const maximum = Math.max(8, innerHeight - height - 8), minimum = Math.min(140, maximum);
  bottom.value = Math.max(minimum, Math.min(maximum, bottom.value));
}
function detectDialogs() {
  blocked.value = [...document.querySelectorAll('.el-overlay, [role="dialog"]')].some(element => {
    if (element.matches('.tracking-capture-drawer') || element.closest('.tracking-capture-drawer') || element.querySelector('.tracking-capture-drawer')) return false;
    const style = getComputedStyle(element), box = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
  });
}
function show() {
  if (dragged) return;
  flowContext.value = {...context.value}; candidatesReady.value = false; candidateError.value = ''; open.value = true;
  loadCandidates();
}
async function loadCandidates() {
  const request = ++candidateRequest;
  candidatesReady.value = false; loadingCandidates.value = true; candidateError.value = '';
  try {
    const data = await tracking('candidates/', 'get', null, flowContext.value);
    if (!alive || request !== candidateRequest || !open.value) return;
    candidates.value = data; candidatesReady.value = true;
  } catch (e) { if (alive && request === candidateRequest) candidateError.value = e.message || '办理人加载失败，请重试'; }
  finally { if (alive && request === candidateRequest) loadingCandidates.value = false; }
}
function created() { open.value = false; window.dispatchEvent(new Event('issue-tracking-updated')); }
watch(open, value => { if (!value) { candidateRequest += 1; loadingCandidates.value = false; } });
watch(() => route.path, async () => {
  const request = ++routeRequest;
  open.value = false; record.value = null; rules.value = [];
  try { const result = await tracking('candidates/'); if (alive && request === routeRequest) rules.value = result.rules || []; }
  catch { if (alive && request === routeRequest) rules.value = []; }
}, {immediate: true});
function start(e) { origin = {x: e.clientX, y: e.clientY, right: right.value, bottom: bottom.value}; dragged = false; }
function move(e) {
  if (!origin) return;
  const dx = e.clientX - origin.x, dy = e.clientY - origin.y;
  if (!dragged && Math.abs(dx) + Math.abs(dy) > 5) { dragged = true; e.currentTarget.setPointerCapture?.(e.pointerId); }
  if (!dragged) return;
  right.value = origin.right - dx; bottom.value = origin.bottom - dy; clamp();
}
function stop() { origin = null; }
function cancel() { origin = null; dragged = true; }
onMounted(() => { clamp(); detectDialogs(); window.addEventListener('issue-tracking-context', receive); window.addEventListener('resize', clamp); observer = new MutationObserver(detectDialogs); observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'aria-hidden']}); });
onBeforeUnmount(() => { alive = false; candidateRequest += 1; routeRequest += 1; observer?.disconnect(); window.removeEventListener('issue-tracking-context', receive); window.removeEventListener('resize', clamp); });
</script>
<style scoped>
.tracking-float{position:fixed;z-index:1999;touch-action:none;cursor:move;display:flex;align-items:center;border-radius:22px;background:white;box-shadow:0 3px 12px #0f172a20}.tracking-float .collapse-button{margin-left:0;padding:8px;min-width:24px}.tracking-float :deep(.el-button--primary){margin:0}
</style>
