<template>
  <div class="field-designer">
    <aside class="field-library" aria-label="可用字段">
      <h2>字段库</h2>
      <p>拖入行、列或指标区域组合分析，也可用添加按钮操作。</p>
      <label class="field-search">搜索字段<input v-model="search" placeholder="如店铺、销量、库存" /></label>
      <section v-for="group in groups" :key="group.kind">
        <h3>{{ group.title }}</h3>
        <article v-for="item in group.items.filter(item => item.label.includes(search))" :key="item.key"
          class="library-field" draggable="true" :data-field="item.key" :data-kind="group.kind"
          @dragstart="start($event, { key: item.key, kind: group.kind })" @dragend="dragging = null" :title="item.definition || item.label">
          <span>⠿ {{ item.label }}</span>
          <button type="button" :aria-label="`添加${item.label}到${zoneLabels[group.zone]}`" @click="add({ key: item.key, kind: group.kind }, group.zone)">＋</button>
        </article>
      </section>
    </aside>
    <div class="field-zones">
      <p class="field-hint">行列决定分组，指标决定结果。金额保留币种；修改后点击查询。</p>
      <section v-for="zone in ['rows', 'columns', 'metrics', 'filters']" :key="zone" class="field-zone"
        :class="{ 'can-drop': dragging && compatible(zone) }" :data-zone="zone" :aria-label="zoneLabels[zone]"
        @dragover.prevent="" @drop.prevent="drop($event, zone)">
        <h3>{{ zoneLabels[zone] }} <small>{{ limits[zone] }}</small></h3>
        <div class="field-chips">
          <article v-for="(key, index) in keys(zone)" :key="key" class="field-chip" draggable="true" :data-field="key"
            @dragstart="start($event, { key, kind: kind(zone) })" @dragend="dragging = null"
            @dragover.stop.prevent="" @drop.stop.prevent="drop($event, zone, index)">
            <span>⠿ {{ label(key, zone) }}</span>
            <button v-if="zone === 'rows' || zone === 'columns'" type="button" :aria-label="`将${label(key, zone)}移到${zone === 'rows' ? '列' : '行'}`"
              @click="add({ key, kind: 'dimension' }, zone === 'rows' ? 'columns' : 'rows')">{{ zone === 'rows' ? '→列' : '→行' }}</button>
            <button type="button" :disabled="index === 0" :aria-label="`前移${label(key, zone)}`" @click="add({ key, kind: kind(zone) }, zone, index - 1)">←</button>
            <button type="button" :aria-label="`移除${label(key, zone)}`" @click="remove(key, zone)">×</button>
          </article>
          <span v-if="!keys(zone).length" class="drop-placeholder">拖入{{ zoneLabels[zone] }}字段</span>
        </div>
      </section>
      <p v-if="notice" role="status" class="field-notice">{{ notice }}</p>
    </div>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue';
import { clone, datasetFilters, fieldLayout, filterLabel, moveField, removeField } from './biLayout';
const props = defineProps({ dataset: { type: Object, required: true }, config: { type: Object, required: true } });
const emit = defineEmits(['change']);
const search = ref(''), dragging = ref(null), notice = ref('');
const zoneLabels = { rows: '行维度', columns: '列维度', metrics: '指标', filters: '筛选' };
const limits = { rows: '行列合计最多 6 个', columns: '最多 3 个 · 自动切换透视表', metrics: '最多 8 个', filters: '仅显示所选筛选控件' };
const layout = computed(() => fieldLayout(props.config, props.dataset));
const groups = computed(() => [
  { kind: 'dimension', zone: 'rows', title: '维度', items: props.dataset.dimensions },
  { kind: 'metric', zone: 'metrics', title: '指标', items: props.dataset.metrics },
  { kind: 'filter', zone: 'filters', title: '筛选控件', items: datasetFilters(props.dataset).map(key => ({ key, label: filterLabel(key) })) }
]);
const kind = zone => zone === 'metrics' ? 'metric' : zone === 'filters' ? 'filter' : 'dimension';
const compatible = zone => dragging.value?.kind === kind(zone);
const keys = zone => zone === 'metrics' ? props.config.metrics : layout.value[zone];
const label = (key, zone) => zone === 'filters' ? filterLabel(key) : [...props.dataset.dimensions, ...props.dataset.metrics].find(item => item.key === key)?.label || key;
function start(event, field) {
  dragging.value = field;
  event.dataTransfer?.setData('application/x-report-field', JSON.stringify({ ...field, dataset: props.dataset.id }));
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
}
function add(field, zone, index) {
  const next = moveField(props.config, props.dataset, field, zone, index);
  notice.value = next ? '' : '无法添加：请核对字段类型及数量上限。';
  if (next) emit('change', next);
}
function drop(event, zone, index) {
  try {
    const field = JSON.parse(event.dataTransfer.getData('application/x-report-field'));
    if (field.dataset === props.dataset.id) add(field, zone, index);
  } catch { notice.value = '请从当前数据集的字段库拖入字段。'; }
  dragging.value = null;
}
function remove(key, zone) {
  const next = removeField(props.config, props.dataset, key, zone);
  notice.value = next ? '' : '至少保留一个维度和指标；金额指标须保留币种维度。';
  if (next) emit('change', clone(next));
}
</script>
<style scoped>
.field-designer { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; min-width: 0; }
.field-library, .field-zone { border: 1px solid #dce3ec; background: #fff; border-radius: 8px; padding: 14px; min-width: 0; }
.field-library { max-height: 530px; overflow: auto; }
h2 { margin: 0; font-size: 16px; } h3 { margin: 12px 0 8px; font-size: 13px; }
p, small, .drop-placeholder { color: #627086; font-size: 12px; line-height: 1.6; }
.field-search { display: grid; gap: 5px; font-size: 12px; }.field-search input { padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; width: 100%; box-sizing: border-box; }
.library-field, .field-chip { display: flex; align-items: center; gap: 5px; justify-content: space-between; font-size: 12px; margin-top: 6px; padding: 6px 8px; border-radius: 4px; background: #f3f5fa; cursor: grab; }
.library-field span, .field-chip span { overflow-wrap: anywhere; }
button { border: 0; background: transparent; cursor: pointer; padding: 4px; color: #5941c6; white-space: nowrap; }
button:disabled { opacity: .35; cursor: default; } button:focus-visible, article:focus-visible { outline: 2px solid #5941c6; }
.field-zones { display: grid; align-content: start; gap: 10px; min-width: 0; }.field-hint { margin: 0; }
.field-zone h3 { margin: 0 0 8px; display: flex; gap: 10px; flex-wrap: wrap; }
.field-chips { display: flex; gap: 6px; flex-wrap: wrap; min-height: 34px; align-items: center; }.field-chip { margin: 0; }
.can-drop { border-color: #6952d9; background: #f8f6ff; }.field-notice { color: #92400e; margin: 0; }
@media (max-width: 760px) { .field-designer { grid-template-columns: minmax(0, 1fr); }.field-library { max-height: 230px; } }
</style>
