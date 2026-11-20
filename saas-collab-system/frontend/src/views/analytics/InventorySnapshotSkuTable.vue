<template>
  <section v-loading="loading" class="inventory-sku-details" aria-label="SKU 库存快照">
    <div v-if="error" class="inventory-sku-error">
      <el-alert :title="error" type="error" :closable="false" show-icon />
      <el-button @click="load">重试</el-button>
    </div>
    <el-table :data="rows" row-key="id" stripe empty-text="暂无 SKU 快照" @sort-change="changeSort"
      @row-click="row => emit('row-click', row)">
      <el-table-column label="商品图片" width="94">
        <template #default="{ row }">
          <InventorySnapshotImage :url="row.image_url" :alt="row.internal_sku_id ? row.internal_sku : row.source_sku" />
        </template>
      </el-table-column>
      <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop"
        :label="column.label" :min-width="column.width || 120" :sortable="column.sortable"
        show-overflow-tooltip>
        <template #default="{ row }">
          {{ row[column.prop] === '' || row[column.prop] == null ? column.empty || '—' : row[column.prop] }}
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total > pageSize" v-model:current-page="page" background
      layout="prev, pager, next, total" :page-size="pageSize" :total="total" @current-change="load" />
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { fetchInventoryAnalysis } from '../../api/analytics';
import { formatApiError } from '../../api/request';
import InventorySnapshotImage from './InventorySnapshotImage.vue';

const props = defineProps({
  query: { type: Object, required: true },
  groupKey: { type: String, required: true },
  columns: { type: Array, required: true }
});
const emit = defineEmits(['row-click']);
const rows = ref([]);
const loading = ref(false);
const error = ref('');
const page = ref(1);
const total = ref(0);
const ordering = ref('');
const pageSize = 20;
let activeRequest;

async function load() {
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchInventoryAnalysis({
      ...props.query, group_key: props.groupKey, ordering: ordering.value, page: page.value, page_size: pageSize
    }, { signal: request.signal });
    if (request.signal.aborted) return;
    if (!response?.success || response.data?.detail_view !== 'sku') {
      error.value = response?.success ? 'SKU 快照暂不可用' : formatApiError(response);
      rows.value = [];
      total.value = 0;
      return;
    }
    rows.value = response.data.results;
    total.value = response.data.count;
  } catch (failure) {
    if (request.signal.aborted) return;
    error.value = formatApiError(failure?.response || { message: failure?.message });
    rows.value = [];
    total.value = 0;
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}

function changeSort({ prop, order }) {
  const next = order ? (order === 'descending' ? '-' : '') + prop : '';
  if (next === ordering.value) return;
  ordering.value = next;
  page.value = 1;
  load();
}

watch(() => [props.query, props.groupKey], () => {
  page.value = 1;
  load();
}, { immediate: true });
onBeforeUnmount(() => activeRequest?.abort());
</script>

<style scoped>
.inventory-sku-details { padding: 12px 16px; }
.inventory-sku-details :deep(.el-pagination) { justify-content: flex-end; margin-top: 12px; }
.inventory-sku-error { display: flex; align-items: center; gap: 8px; }
</style>
