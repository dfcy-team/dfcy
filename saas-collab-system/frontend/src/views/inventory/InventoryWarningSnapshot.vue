<template>
  <form class="warning-filters" @submit.prevent="apply">
    <el-select v-model="filters.country_id" aria-label="预警国家" placeholder="选择国家">
      <el-option v-for="country in countries" :key="country.id" :label="country.name" :value="country.id" />
    </el-select>
    <el-select v-model="filters.warning_type" aria-label="预警类型">
      <el-option label="全部预警类型" value="all" />
      <el-option v-for="(label, code) in labels" :key="code" :label="label" :value="code" />
    </el-select>
    <el-input v-model="filters.search" aria-label="商品搜索" placeholder="搜索 SPU / SKU" maxlength="200" clearable />
    <el-button native-type="submit" :loading="loading">查询</el-button>
  </form>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <p v-else>{{ state.updated_at ? '快照更新：' + state.updated_at : '请选择国家查看已发布快照。' }}</p>
  <el-table v-loading="loading" :data="state.results || []" empty-text="暂无已发布预警快照" border>
    <el-table-column prop="product_name" label="商品" min-width="180" />
    <el-table-column prop="spu_code" label="SPU" min-width="130" />
    <el-table-column label="ABC" width="100"><template #default="{ row }">{{ row.abc?.spu_grade || '—' }}</template></el-table-column>
    <el-table-column label="预警" min-width="180">
      <template #default="{ row }">{{ (row.warnings || []).map(code => labels[code] || code).join('、') || '—' }}</template>
    </el-table-column>
    <el-table-column label="规格" width="120">
      <template #default="{ row }"><el-button link type="primary" @click="openDetails(row)">查看规格</el-button></template>
    </el-table-column>
  </el-table>
  <el-drawer v-model="detailsOpen" title="库存预警规格" size="min(760px, 96vw)" @close="closeDetails">
    <el-alert v-if="detailsError" :title="detailsError" type="error" :closable="false" />
    <el-table v-loading="detailsLoading" :data="details" empty-text="暂无规格快照" border>
      <el-table-column prop="sku_code" label="SKU" min-width="145" />
      <el-table-column prop="product_name" label="商品" min-width="150" />
      <el-table-column label="补货" width="120">
        <template #default="{ row }">
          <router-link v-if="row.sku_code && applied.country_id" :to="{ path: '/inventory/replenishment', query: { country_id: String(applied.country_id), search: row.sku_code } }">查看建议</router-link>
        </template>
      </el-table-column>
      <el-table-column prop="available_stock" label="可售库存" width="105" />
      <el-table-column label="预警" min-width="150">
        <template #default="{ row }">{{ (row.warning?.warnings || []).map(code => labels[code] || code).join('、') || '—' }}</template>
      </el-table-column>
    </el-table>
  </el-drawer>
  <el-pagination :current-page="page" :page-size="20" :total="state.count || 0" layout="prev, pager, next" @current-change="loadPage" />
</template>

<script setup>
import { onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { fetchInventoryWarnings } from '../../api/alerts';

const labels = {
  forecast_stockout: '预计缺货', key_variant_shortage: '关键规格缺货',
  supply_risk: '供应风险', excess_stock: '库存偏多', new_product: '新品观察',
};
const filters = reactive({ country_id: null, warning_type: 'all', search: '' });
const countries = ref([]), state = ref({}), page = ref(1), loading = ref(false), error = ref('');
const detailsOpen = ref(false), detailsLoading = ref(false), details = ref([]), detailsError = ref('');
let applied = {}, controller, detailController;

function closeDetails() {
  detailController?.abort();
  detailsOpen.value = false;
  detailsLoading.value = false;
  details.value = [];
  detailsError.value = '';
}

async function openDetails(row) {
  if (!applied.country_id || !row.spu_id) return;
  closeDetails();
  const request = new AbortController();
  detailController = request;
  detailsOpen.value = true;
  detailsLoading.value = true;
  try {
    const response = await fetchInventoryWarnings({ country_id: applied.country_id, spu_id: row.spu_id }, request.signal);
    if (request.signal.aborted) return;
    if (!response?.success) throw new Error(response?.message || '读取规格快照失败。');
    details.value = response.data?.results || [];
  } catch (failure) {
    if (!request.signal.aborted) detailsError.value = failure.message || '读取规格快照失败。';
  } finally {
    if (!request.signal.aborted) detailsLoading.value = false;
  }
}

async function loadPage(next) {
  closeDetails();
  controller?.abort();
  const request = new AbortController();
  controller = request;
  page.value = next;
  state.value = { ...state.value, results: [] };
  error.value = '';
  loading.value = true;
  try {
    const response = await fetchInventoryWarnings({ ...applied, page: next }, request.signal);
    if (request.signal.aborted) return;
    if (!response?.success) throw new Error(response?.message || '读取预警快照失败。');
    state.value = response.data || {};
    if (state.value.countries) countries.value = state.value.countries;
  } catch (failure) {
    if (!request.signal.aborted) error.value = failure.message || '读取预警快照失败。';
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
function apply() {
  if (!filters.country_id) {
    error.value = '请选择国家。';
    return;
  }
  applied = { ...filters, search: filters.search.trim() };
  state.value = {};
  loadPage(1);
}
onMounted(() => loadPage(1));
onBeforeUnmount(() => { controller?.abort(); detailController?.abort(); });
</script>

<style scoped>
.warning-filters{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.warning-filters :deep(.el-select),.warning-filters :deep(.el-input){width: min(220px, 100%)}
</style>
