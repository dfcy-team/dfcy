<template>
  <section class="dashboard-builder" :aria-busy="loading">
    <header class="dashboard-heading"><div><h1>{{ name || `${board.module}组合看板` }}</h1><p>从左侧拖入组件，拖动标题调整顺序，拖动右下角调整大小。点击结果可联动，再查看业务明细。</p></div>
      <div class="dashboard-actions"><el-button :loading="loading" :disabled="!board.widgets.length" type="primary" @click="run">刷新分析</el-button>
        <el-button v-if="canSave" :disabled="!board.widgets.length || loading || dirty || hasErrors" @click="saveOpen = true">保存看板</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="dashboard-global"><label>归属模块<el-select v-model="board.module" :disabled="board.widgets.length > 0" aria-label="看板归属模块">
      <el-option v-for="module in dashboardModules" :key="module" :label="module" :value="module" /></el-select></label>
      <el-button :disabled="loading" @click="useTemplate">加载业务模板</el-button><el-button :disabled="loading" @click="clearBoard">清空组件</el-button>
      <label v-for="key in shownFilters" :key="key">{{ filterLabel(key) }}
        <el-date-picker v-if="key.startsWith('date_')" v-model="board.filters[key]" type="date" value-format="YYYY-MM-DD" clearable />
        <el-input v-else v-model.trim="board.filters[key]" :placeholder="key === 'currency' ? '原币 / 成本币种，如 PHP、CNY' : '全部'" clearable />
      </label>
    </div>
    <p class="dashboard-note">全局条件仅作用于支持该字段的组件，未适用条件会逐项标出。销售和库存之间不假设 SKU 映射；金额分别保留交易币种或成本币种。</p>
    <p v-if="dirty && Object.keys(states).length" role="status" class="dirty-banner">分析配置已修改，点击刷新分析后更新结果；当前结果暂不能联动或穿透。</p>
    <div v-if="link" class="link-banner"><span>联动选择：{{ linkLabel }}</span><el-button size="small" @click="clearLink">清除联动</el-button>
      <el-button v-if="selectedSource && canDrillSource" size="small" :disabled="dirty || loading" @click="drillSelected">查看业务明细</el-button>
      <el-button v-if="selectedSource?.config.dataset === 'inventory_value' && !selectedSource.config.dimensions.includes('sku')" size="small" :disabled="dirty || loading" @click="expandValuation">展开 SKU 成本明细</el-button>
    </div>
    <div class="dashboard-workspace">
      <aside class="component-library"><h2>组件库</h2><label>授权数据集<el-select v-model="libraryDataset" aria-label="组件数据集">
        <el-option v-for="item in availableDatasets" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
        <article v-for="item in componentTypes" :key="item.value" draggable="true" class="component-tile" :data-component="item.value"
          @dragstart="startComponent($event, item.value)"><span>⠿ {{ item.label }}</span><button type="button" :aria-label="`添加${item.label}`" :disabled="!libraryDataset || board.widgets.length >= 8" @click="addWidget(item.value)">＋</button></article>
        <p>{{ board.widgets.length }} / 8 个组件。只查询当前授权数据，最多同时读取 3 个组件。</p>
        <el-empty v-if="!availableDatasets.length" description="此模块暂无已授权数据集。" />
      </aside>
      <div class="dashboard-canvas" aria-label="看板画布" @dragover.prevent="" @drop.prevent="dropOnCanvas">
        <article v-for="(widget, index) in board.widgets" :key="widget.id" class="dashboard-widget" :data-widget="widget.id"
          :style="{ gridColumn: `span ${widget.width}`, height: `${widget.height}px` }" @dragover.prevent="" @drop.stop.prevent="dropOnWidget($event, index)">
          <header class="widget-header" draggable="true" @dragstart="startWidget($event, widget.id)">
            <strong>⠿ {{ widget.title }}</strong><div class="widget-tools">
              <button type="button" :disabled="index === 0" :aria-label="`前移组件${widget.title}`" @click="moveWidget(widget.id, index - 1)">←</button>
              <button type="button" :aria-label="`设置组件${widget.title}`" @click="editId = widget.id">设置</button>
              <button v-if="canExport(widget)" type="button" :disabled="dirty || loading || !states[widget.id]?.result || states[widget.id]?.result?.truncated" :aria-label="`导出组件${widget.title}`" @click="exportWidget(widget)">导出</button>
              <button type="button" :aria-label="`移除组件${widget.title}`" @click="removeWidget(widget.id)">×</button>
            </div></header>
          <div class="widget-body" v-loading="states[widget.id]?.loading">
            <p class="widget-source">{{ metadata(widget)?.name }} · {{ widget.config.dataset === 'inventory_value' ? '成本币种' : '来源原币 / 数量' }}</p>
            <p v-if="states[widget.id]?.ignored?.length" class="widget-warning">未适用条件：{{ states[widget.id].ignored.map(filterLabel).join('、') }}</p>
            <p v-if="states[widget.id]?.linked?.length" class="widget-linked">已联动：{{ states[widget.id].linked.map(filterLabel).join('、') }}</p>
            <el-alert v-if="states[widget.id]?.error" :title="states[widget.id].error" type="error" :closable="false" />
            <template v-if="states[widget.id]?.result && metadata(widget)">
              <p class="widget-freshness">{{ states[widget.id].result.count }} 个分组 · 更新 {{ states[widget.id].result.refreshed_at || '未提供' }} · {{ states[widget.id].result.cached ? '缓存' : '本次计算' }}</p>
              <p v-if="states[widget.id].result.truncated" class="widget-warning">结果超过分组上限，请缩小筛选范围。</p>
              <ReportResult :result="states[widget.id].result" :config="states[widget.id].result.config" :dataset="metadata(widget)" :type="widget.type"
                interaction="select" :show-table="false" :max-height="widget.height - 120" @select="selectRow(widget, $event)" />
            </template>
            <el-empty v-else-if="!states[widget.id]?.loading && !states[widget.id]?.error" description="点击刷新分析读取数据。" />
          </div>
          <button class="resize-handle" type="button" :aria-label="`调整组件${widget.title}大小`" @pointerdown.prevent="startResize($event, widget)" @keydown.right.prevent="widget.width = 12" @keydown.left.prevent="widget.width = 6" @keydown.up.prevent="widget.height = Math.max(240, widget.height - 40)" @keydown.down.prevent="widget.height = Math.min(720, widget.height + 40)">↘</button>
        </article>
        <div v-if="!board.widgets.length" class="empty-canvas">拖入指标卡、趋势图、排行榜或透视表，也可点击“加载业务模板”。</div>
      </div>
    </div>
    <el-drawer v-model="editOpen" title="组件设置" size="min(620px, 96vw)" :before-close="closeEditor">
      <div v-if="editing && metadata(editing)" class="widget-editor">
        <label>组件名称<el-input v-model.trim="editing.title" maxlength="100" /></label>
        <label>展示方式<el-select v-model="editing.type" @change="changeType"><el-option v-for="item in componentTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
        <label>显示指标<el-select v-model="editing.config.chart_metric"><el-option v-for="key in editing.config.metrics" :key="key" :label="metadata(editing).metrics.find(item => item.key === key)?.label || key" :value="key" /></el-select></label>
        <div class="size-controls"><label>宽度<el-select v-model="editing.width"><el-option label="半行" :value="6" /><el-option label="整行" :value="12" /></el-select></label><label>高度<el-input-number v-model="editing.height" :min="240" :max="720" :step="40" :precision="0" /></label></div>
        <ReportFieldDesigner :config="editing.config" :dataset="metadata(editing)" @change="changeFields" />
        <label v-for="key in editorFilters" :key="key">组件筛选 · {{ filterLabel(key) }}
          <el-date-picker v-if="key.startsWith('date_')" v-model="editing.config.filters[key]" type="date" value-format="YYYY-MM-DD" clearable />
          <el-checkbox v-else-if="key === 'include_virtual'" v-model="editing.config.filters[key]">包含虚拟商品</el-checkbox>
          <el-input v-else v-model.trim="editing.config.filters[key]" clearable placeholder="全部" />
        </label>
        <label>结果排序<el-select v-model="editing.config.ordering" clearable><template v-for="key in [...editing.config.dimensions, ...editing.config.metrics]" :key="key"><el-option :label="`${key} · 升序`" :value="key" /><el-option :label="`${key} · 降序`" :value="`-${key}`" /></template></el-select></label>
        <p class="dashboard-note">全局条件和联动会覆盖对应的组件筛选；配置改变后需要刷新分析。</p>
        <el-button type="primary" @click="editId = ''; run()">应用并刷新</el-button>
      </div>
    </el-drawer>
    <el-dialog v-model="saveOpen" title="保存组合看板" width="min(440px, 92vw)"><el-input v-model.trim="saveName" placeholder="看板名称" maxlength="100" />
      <p><el-checkbox v-model="shared">共享给当前租户有全部组件业务权限的用户</el-checkbox></p><p class="dashboard-note">只保存布局和查询配置，不保存业务数据。打开时按查看者权限重新查询。</p>
      <template #footer><el-button :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchReportDatasets, queryReport, saveReportView } from '../../api/reporting';
import { createReportExport } from '../../api/reportExports';
import ReportFieldDesigner from './ReportFieldDesigner.vue';
import ReportResult from './ReportResult.vue';
import { clone, datasetFilters, fieldLayout, filterLabel } from './biLayout';
import { componentTypes, dashboardModules, dashboardTemplate, drillLocation, globalFilterKeys, moduleDatasets, newWidget, queryWithLink, selectionLink } from './biDashboard';
const props = defineProps({ viewConfig: { type: Object, default: null }, module: { type: String, default: '经营分析' }, name: { type: String, default: '' } });
const emit = defineEmits(['saved']);
const router = useRouter(), auth = useAuthStore();
const board = reactive({ kind: 'dashboard', version: 1, module: props.module, filters: {}, widgets: [] });
const datasets = ref([]), states = reactive({}), libraryDataset = ref(''), editId = ref(''), link = ref(null), loading = ref(false), error = ref(''), applied = ref('');
const saveOpen = ref(false), saveName = ref(props.name), shared = ref(false), saving = ref(false);
let sequence = 0, nextId = 1, controllers = [], cleanupResize;
const canSave = computed(() => auth.currentUser?.is_superuser || auth.hasPermission?.('reports.view'));
const allowed = code => auth.currentUser?.is_superuser || auth.hasPermission?.(code);
const canExport = widget => allowed('reports.export') && (['finance', 'inventory_value'].includes(widget.config.dataset) ? allowed('finance.export') : ['sales', 'sales_skus', 'refunds'].includes(widget.config.dataset) ? allowed('sales_management.export') : true);
const availableDatasets = computed(() => moduleDatasets(datasets.value, board.module));
const metadata = widget => datasets.value.find(item => item.id === widget.config.dataset);
const editing = computed(() => board.widgets.find(item => item.id === editId.value));
const editOpen = computed({ get: () => Boolean(editing.value), set: value => { if (!value) editId.value = ''; } });
const editorFilters = computed(() => editing.value?.config.field_layout?.filters || datasetFilters(editing.value && metadata(editing.value)));
const shownFilters = computed(() => globalFilterKeys.filter(key => board.widgets.some(widget => datasetFilters(metadata(widget)).includes(key))));
const signature = computed(() => JSON.stringify({ filters: board.filters, widgets: board.widgets.map(({ id, config }) => ({ id, config })).sort((a, b) => a.id.localeCompare(b.id)), link: link.value }));
const dirty = computed(() => !applied.value || applied.value !== signature.value);
const hasErrors = computed(() => board.widgets.some(widget => !states[widget.id]?.result || states[widget.id]?.error));
const selectedSource = computed(() => board.widgets.find(item => item.id === link.value?.source));
const linkLabel = computed(() => link.value ? Object.entries({ ...link.value.filters, ...link.value.local }).map(([key, value]) => `${filterLabel(key)}=${value}`).join(' · ') || '此分组没有可联动的已关联维度' : '');
const canDrillSource = computed(() => selectedSource.value && canAccessPath(auth.currentUser, metadata(selectedSource.value)?.path));
function stopQueries() { sequence++; controllers.forEach(controller => controller.abort()); controllers = []; loading.value = false; }
function clearBoard() { stopQueries(); board.widgets = []; board.filters = {}; link.value = null; editId.value = ''; Object.keys(states).forEach(key => delete states[key]); applied.value = ''; }
function useTemplate() { clearBoard(); Object.assign(board, dashboardTemplate(board.module, datasets.value)); nextId = board.widgets.length + 1; run(); }
function addWidget(type, index = board.widgets.length) {
  const dataset = availableDatasets.value.find(item => item.id === libraryDataset.value);
  if (!dataset || board.widgets.length >= 8) { error.value = '最多放置 8 个已授权组件。'; return; }
  while (board.widgets.some(item => item.id === `widget-${nextId}`)) nextId++;
  board.widgets.splice(index, 0, newWidget(dataset, type, `widget-${nextId++}`)); error.value = '';
}
function moveWidget(id, index) { const from = board.widgets.findIndex(item => item.id === id); if (from < 0 || index < 0 || index >= board.widgets.length) return; const [widget] = board.widgets.splice(from, 1); board.widgets.splice(index, 0, widget); }
function removeWidget(id) { board.widgets = board.widgets.filter(item => item.id !== id); delete states[id]; if (link.value?.source === id) link.value = null; }
function startComponent(event, type) { event.dataTransfer.setData('application/x-report-component', JSON.stringify({ dataset: libraryDataset.value, type })); event.dataTransfer.effectAllowed = 'copy'; }
function startWidget(event, id) { event.dataTransfer.setData('application/x-report-widget', id); event.dataTransfer.effectAllowed = 'move'; }
function handleDrop(event, index) {
  const id = event.dataTransfer.getData('application/x-report-widget');
  if (id) { moveWidget(id, Math.min(index, board.widgets.length - 1)); return; }
  try { const data = JSON.parse(event.dataTransfer.getData('application/x-report-component')); if (availableDatasets.value.some(item => item.id === data.dataset) && componentTypes.some(item => item.value === data.type)) { libraryDataset.value = data.dataset; addWidget(data.type, index); } } catch { /* Unrelated external drops are ignored. */ }
}
const dropOnCanvas = event => handleDrop(event, board.widgets.length);
const dropOnWidget = (event, index) => handleDrop(event, index);
function startResize(event, widget) {
  cleanupResize?.();
  const startX = event.clientX, startY = event.clientY, height = widget.height;
  const element = event.currentTarget.closest('.dashboard-widget'), canvas = element.parentElement;
  const initialWidth = element.getBoundingClientRect().width;
  const move = current => { widget.height = Math.round(Math.min(720, Math.max(240, height + current.clientY - startY))); widget.width = initialWidth + current.clientX - startX > canvas.getBoundingClientRect().width * .7 ? 12 : 6; };
  const done = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', done); window.removeEventListener('pointercancel', done); cleanupResize = null; };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', done); window.addEventListener('pointercancel', done); cleanupResize = done;
}
function closeEditor(done) { editId.value = ''; done(); }
function changeType(type) {
  const config = editing.value.config; config.chart = type === 'card' ? 'table' : type;
  if (type === 'pivot' && !config.pivot) { config.pivot = config.dimensions.find(key => key !== 'currency') || config.dimensions[0]; config.field_layout = fieldLayout({ ...config, field_layout: undefined }, metadata(editing.value)); }
}
function changeFields(config) { editing.value.config = config; if (config.field_layout.columns.length) editing.value.type = 'pivot'; }
async function run() {
  stopQueries();
  if (!board.widgets.length) return;
  const current = sequence, widgets = clone(board.widgets), filters = clone(board.filters), selection = clone(link.value);
  const startSignature = signature.value;
  loading.value = true; error.value = '';
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(3, widgets.length) }, async () => {
    while (cursor < widgets.length && current === sequence) {
      const widget = widgets[cursor++], effective = queryWithLink(widget, datasets.value, filters, selection);
      if (!board.widgets.some(item => item.id === widget.id)) continue;
      const controller = new AbortController(); controllers.push(controller);
      states[widget.id] = { loading: true, error: '', result: null, ignored: effective?.ignored || [], linked: effective?.linked || [] };
      try {
        if (!effective) throw new Error('此组件数据集已不可访问。');
        const response = await queryReport(effective.config, controller.signal);
        if (current !== sequence) return;
        if (!states[widget.id] || !board.widgets.some(item => item.id === widget.id)) continue;
        if (!response.success) throw new Error(response.message || '读取失败');
        states[widget.id].result = response.data;
      } catch (failure) {
        if (current === sequence && states[widget.id]) states[widget.id].error = failure.message || '读取失败';
      } finally { if (current === sequence && states[widget.id]) states[widget.id].loading = false; }
    }
  }));
  if (current === sequence) {
    if (signature.value === startSignature) {
      for (const widget of board.widgets) {
        const normalized = states[widget.id]?.result?.config;
        if (normalized) {
          widget.config.dimensions = normalized.dimensions;
          if (normalized.field_layout) widget.config.field_layout = normalized.field_layout;
        }
      }
      applied.value = signature.value;
    } else applied.value = startSignature;
    loading.value = false;
  }
}
function selectRow(widget, row) { if (dirty.value || loading.value) return; link.value = selectionLink(widget, row); run(); }
function clearLink() { link.value = null; run(); }
function drillSelected() {
  const widget = selectedSource.value; if (!widget || dirty.value || loading.value) return;
  const location = drillLocation(widget, link.value.row, states[widget.id].result, metadata(widget));
  if (location && canAccessPath(auth.currentUser, location.path)) router.push(location);
}
function expandValuation() {
  const widget = selectedSource.value; if (!widget || dirty.value || loading.value) return;
  const filters = { ...states[widget.id].result.config.filters };
  for (const key of ['warehouse_id', 'site_code', 'currency']) if (link.value.row[key] != null) filters[key] = link.value.row[key];
  if (link.value.row.currency == null) filters.cost_status = 'missing';
  Object.assign(widget.config, { dimensions: ['warehouse_id', 'sku', 'currency'], metrics: ['on_hand', 'valued_count', 'missing_cost_count', 'inventory_value'], filters, chart: 'table', chart_metric: 'inventory_value', pivot: '', ordering: '', field_layout: { rows: ['warehouse_id', 'sku', 'currency'], columns: [], filters: datasetFilters(metadata(widget)) } });
  widget.type = 'table'; link.value = null; run();
}
async function save() {
  if (dirty.value || loading.value || hasErrors.value) return;
  saving.value = true; error.value = '';
  try {
    const config = clone(board);
    const clean = filters => Object.fromEntries(Object.entries(filters).filter(([, value]) => value != null && value !== ''));
    config.filters = clean(config.filters);
    for (const widget of config.widgets) widget.config.filters = clean(widget.config.filters);
    const response = await saveReportView({ name: saveName.value, config, is_shared: shared.value });
    if (!response.success) throw new Error(response.message); saveOpen.value = false; emit('saved');
  }
  catch (failure) { error.value = failure.message; } finally { saving.value = false; }
}
async function exportWidget(widget) {
  if (dirty.value || loading.value || !canExport(widget) || !states[widget.id]?.result || states[widget.id].result.truncated) return;
  try {
    const response = await createReportExport({ report_type: 'self_service', filters: { config: clone(states[widget.id].result.config) } });
    if (!response.success || response.data.status === 'rejected') throw new Error(response.message || '请缩小结果范围后导出。');
    router.push('/reports/exports');
  } catch (failure) { error.value = failure.message || '导出失败'; }
}
function restore(config) { clearBoard(); Object.assign(board, clone(config)); nextId = board.widgets.length + 1; if (!board.widgets.every(widget => metadata(widget))) { error.value = '看板包含当前角色无法访问的数据集。'; return; } run(); }
watch(availableDatasets, items => { if (!items.some(item => item.id === libraryDataset.value)) libraryDataset.value = items[0]?.id || ''; }, { immediate: true });
watch(() => props.viewConfig, value => { if (value && datasets.value.length) restore(value); });
onMounted(async () => {
  try { const response = await fetchReportDatasets(); if (!response.success) throw new Error(response.message); datasets.value = response.data.datasets || []; if (props.viewConfig) restore(props.viewConfig); else useTemplate(); }
  catch (failure) { error.value = failure.message; }
});
onBeforeUnmount(() => { stopQueries(); cleanupResize?.(); });
defineExpose({ board, states, run, link, addWidget, moveWidget, selectRow, dirty, restore });
</script>
<style scoped>
.dashboard-builder { display: grid; gap: 14px; min-width: 0; color: #172033; }.dashboard-heading, .dashboard-actions, .link-banner { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }.dashboard-heading { justify-content: space-between; } h1 { margin: 0; font-size: 23px; } h2 { margin: 0 0 12px; font-size: 15px; }
.dashboard-heading p, .dashboard-note, .component-library p { margin: 6px 0 0; color: #627086; font-size: 12px; line-height: 1.7; }
.dashboard-global { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; padding: 14px; border: 1px solid #dce3ec; background: #fff; border-radius: 6px; }
label { display: grid; gap: 6px; font-size: 12px; min-width: 0; }.dashboard-global label { width: 170px; }.dashboard-global :deep(.el-input), .dashboard-global :deep(.el-select), .dashboard-global :deep(.el-date-editor) { width: 100%; }
.dashboard-workspace { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 16px; }.component-library { background: #fff; border: 1px solid #dce3ec; border-radius: 6px; padding: 14px; align-self: start; min-width: 0; }.component-library :deep(.el-select) { width: 100%; }
@media (min-width: 1001px) { .component-library { position: sticky; top: 16px; } }
.component-tile { display: flex; align-items: center; justify-content: space-between; padding: 10px; margin-top: 10px; background: #f3f5fa; border-radius: 4px; cursor: grab; font-size: 13px; }
button { cursor: pointer; }.component-tile button, .widget-tools button { background: transparent; border: none; color: #5941c6; padding: 5px; }.component-tile button:disabled, .widget-tools button:disabled { opacity: .4; cursor: default; }
.dashboard-canvas { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; align-content: start; min-height: 360px; min-width: 0; padding: 12px; border: 1px dashed #c7d2e1; border-radius: 6px; background: #f3f6fa; }
.dashboard-widget { min-width: 0; position: relative; background: #fff; border: 1px solid #dce3ec; border-radius: 7px; display: flex; flex-direction: column; overflow: hidden; }.widget-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 12px; background: #fbfcfe; border-bottom: 1px solid #e8edf4; cursor: grab; min-height: 38px; }.widget-header strong { font-size: 13px; overflow-wrap: anywhere; }.widget-tools { white-space: nowrap; }.widget-body { padding: 12px 14px 20px; overflow: auto; min-height: 0; flex: 1; min-width: 0; }
.widget-source, .widget-freshness, .widget-warning, .widget-linked { font-size: 11px; line-height: 1.6; margin: 0 0 7px; overflow-wrap: anywhere; }.widget-source, .widget-freshness { color: #627086; }.widget-warning { color: #92400e; }.widget-linked { color: #5941c6; }
.resize-handle { position: absolute; right: 0; bottom: 0; width: 24px; height: 24px; border: 0; border-radius: 6px 0 0 0; color: #5941c6; background: #f1eefc; cursor: nwse-resize; touch-action: none; }
.empty-canvas { grid-column: 1/-1; padding: 60px 20px; text-align: center; color: #627086; font-size: 13px; }.dirty-banner, .link-banner { padding: 10px 14px; border-radius: 4px; font-size: 12px; }.dirty-banner { background: #fff7e6; color: #92400e; }.link-banner { background: #f2efff; color: #47339b; }
.widget-editor { display: grid; gap: 16px; min-width: 0; }.widget-editor :deep(.field-designer) { grid-template-columns: minmax(0, 1fr); }.widget-editor :deep(.field-library) { max-height: 210px; }.size-controls { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.dashboard-actions :deep(.el-button) { margin: 0; }
@media (max-width: 1000px) { .dashboard-workspace { grid-template-columns: minmax(0, 1fr); }.component-library { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }.component-library h2 { margin: 0; }.component-library label { width: 200px; }.component-tile { margin: 0; }.component-library p { flex-basis: 100%; } }
@media (max-width: 650px) { .dashboard-widget { grid-column: span 12 !important; }.dashboard-global label { width: 100%; }.dashboard-canvas { padding: 6px; }.dashboard-heading { align-items: flex-start; }.widget-header { flex-wrap: wrap; } }
</style>
