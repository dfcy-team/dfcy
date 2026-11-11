<template>
  <AppPage title="分类库存查询" subtitle="按国家查看各类商品最近一次同步的库存和店铺销量。">
    <el-form inline @submit.prevent="apply">
      <el-form-item label="国家">
        <el-select v-model="country" filterable style="width:180px" @change="reset">
          <el-option v-for="item in countries" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="销量周期">
        <el-select v-model="days" style="width:100px">
          <el-option v-for="day in [7,15,30]" :key="day" :value="day" :label="day + ' 天'" />
        </el-select>
      </el-form-item>
      <el-form-item label="商品"><el-input v-model="search" maxlength="160" clearable placeholder="名称、规格、新旧 SKU" /></el-form-item>
      <el-button type="primary" native-type="submit" :disabled="!country">查询</el-button>
    </el-form>
    <div v-if="applied" class="navigation">
      <el-button link type="primary" @click="goRoot">{{ countryName }} · 分类汇总</el-button>
      <span v-for="(node, index) in trail" :key="node.id">
        › <el-button link type="primary" @click="goCategory(index)">{{ node.name }}</el-button>
      </span>
      <span v-if="spu"> › {{ spu.name }}</span>
      <el-button v-if="trail.length && level === 'category'" @click="showProducts">查看本类商品</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="summary" class="metrics">
      <div v-for="[label, value] in metrics" :key="label"><span>{{ label }}</span><strong>{{ format(value) }}</strong></div>
    </div>
    <el-table v-loading="loading" :data="rows" :empty-text="applied ? '当前条件暂无数据' : '请选择国家并点击查询'">
      <el-table-column :label="level === 'category' ? '类目' : level === 'spu' ? '商品 / SPU' : '商品规格 / SKU'" min-width="240">
        <template #default="{row}">
          <el-button v-if="level !== 'sku'" link type="primary" @click="enter(row)">{{ row.name }}</el-button>
          <div v-else>{{ row.specification || row.name }}</div>
          <small v-if="row.code">{{ row.code }}<span v-if="row.legacy"> · 旧 SKU {{ row.legacy }}</span></small>
        </template>
      </el-table-column>
      <el-table-column v-if="level === 'category'" label="商品款数"><template #default="{row}">{{ row.spu_count }}</template></el-table-column>
      <el-table-column v-if="level !== 'sku'" label="规格数"><template #default="{row}">{{ row.sku_count }}</template></el-table-column>
      <el-table-column label="最近同步可售库存"><template #default="{row}">{{ format(row.available) }}</template></el-table-column>
      <el-table-column :label="'近 ' + (applied?.days || days) + ' 天销量'"><template #default="{row}">{{ format(row.sales) }}</template></el-table-column>
      <el-table-column label="查看明细" min-width="165">
        <template #default="{row}">
          <el-button v-if="level === 'category'" link type="primary" @click="enter(row, true)">查看本类商品</el-button>
          <template v-else>
            <el-button link type="primary" @click="openDetail(row, 'stores')">店铺销售</el-button>
            <el-button v-if="level === 'sku'" link type="primary" @click="openDetail(row, 'warehouses')">仓库库存</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="count > 20" :current-page="page" :page-size="20" :total="count" layout="total, prev, pager, next" @current-change="changePage" />
    <p v-if="applied" class="note">汇总包含当前筛选范围的全部结果。销量按授权店铺已同步成交统计，组合商品按实际售卖的 SKU 统计。</p>
    <el-dialog v-model="detailOpen" :title="detailTitle" width="min(720px, 95vw)" @close="invalidateDetail">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-table v-loading="detailLoading" :data="detailRows" empty-text="暂无数据">
        <template v-if="detailLevel === 'stores'">
          <el-table-column prop="sales_order__store__name" label="店铺" />
          <el-table-column prop="sales_order__store__platform__platform_type" label="平台" />
          <el-table-column prop="units" label="销量" />
          <el-table-column label="销售额"><template #default="{row}">{{ row.currency }} {{ format(row.amount) }}</template></el-table-column>
        </template>
        <template v-else>
          <el-table-column prop="name" label="仓库" />
          <el-table-column label="最近同步可售库存"><template #default="{row}">{{ format(row.available) }}</template></el-table-column>
        </template>
      </el-table>
      <el-pagination v-if="detailCount > 20" :current-page="detailPage" :page-size="20" :total="detailCount" layout="total, prev, pager, next" @current-change="loadDetail" />
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { requestApi } from '../../api/request';

const countries = ref([]), country = ref(null), days = ref(30), search = ref('');
const applied = ref(null), trail = ref([]), spu = ref(null), level = ref('category');
const rows = ref([]), summary = ref(null), count = ref(0), page = ref(1), loading = ref(false), error = ref('');
const detailOpen = ref(false), detailTitle = ref(''), detailLevel = ref(''), detailRows = ref([]);
const detailCount = ref(0), detailPage = ref(1), detailLoading = ref(false), detailError = ref('');
let sequence = 0, detailSequence = 0, detailParams;
let mainController, detailController;

const countryName = computed(() => countries.value.find(item => item.id === applied.value?.country_id)?.name);
const metrics = computed(() => [
  ['商品款数', summary.value?.spu_count], ['规格数', summary.value?.sku_count],
  ['最近同步可售库存', summary.value?.available], ['近 ' + applied.value?.days + ' 天销量', summary.value?.sales],
]);
function format(value) {
  return value == null ? '暂无数据' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}
async function fetchRows(params, signal) {
  const response = await requestApi({ method: 'get', url: '/api/internal/commerce/inventory/category-query/', params, signal });
  if (!response.success) throw new Error(response.message || '读取失败，请重试');
  return response.data;
}
function invalidateDetail() {
  detailSequence++;
  detailController?.abort();
}
function reset() {
  sequence++;
  mainController?.abort();
  invalidateDetail();
  detailOpen.value = false;
  applied.value = null;
  rows.value = [];
  count.value = 0;
  summary.value = null;
  trail.value = [];
  spu.value = null;
  loading.value = false;
  error.value = '';
}
function apply() {
  if (!country.value) return;
  reset();
  applied.value = { country_id: country.value, days: days.value, search: search.value.trim() };
  goRoot();
}
function goRoot() {
  trail.value = [];
  spu.value = null;
  level.value = 'category';
  changePage(1);
}
function goCategory(index) {
  const node = trail.value[index];
  trail.value = trail.value.slice(0, index + 1);
  spu.value = null;
  level.value = node.has_children ? 'category' : 'spu';
  changePage(1);
}
function showProducts() {
  spu.value = null;
  level.value = 'spu';
  changePage(1);
}
function enter(row, products = false) {
  if (level.value === 'category') {
    trail.value = [...trail.value, row];
    level.value = row.has_children && !products ? 'category' : 'spu';
  } else {
    spu.value = row;
    level.value = 'sku';
  }
  changePage(1);
}
function scope() {
  const category = trail.value.at(-1);
  return { ...applied.value, ...(category && { category_id: category.id }) };
}
async function changePage(next) {
  const seq = ++sequence;
  mainController?.abort();
  mainController = new AbortController();
  page.value = next;
  loading.value = true;
  rows.value = [];
  summary.value = null;
  count.value = 0;
  error.value = '';
  try {
    const data = await fetchRows({ ...scope(), level: level.value,
      ...(spu.value && { spu_id: spu.value.id }), offset: (next - 1) * 20 }, mainController.signal);
    if (seq !== sequence) return;
    rows.value = data.results;
    count.value = data.count;
    summary.value = data.summary;
  } catch (err) {
    if (seq === sequence) error.value = err.message;
  } finally {
    if (seq === sequence) loading.value = false;
  }
}
function openDetail(row, kind) {
  detailLevel.value = kind;
  detailTitle.value = row.name + (kind === 'stores' ? ' · 店铺销售' : ' · 仓库库存');
  detailParams = { ...scope(), level: kind,
    ...(level.value === 'spu' ? { spu_id: row.id } : { sku_id: row.id }) };
  detailOpen.value = true;
  loadDetail(1);
}
async function loadDetail(next) {
  invalidateDetail();
  const seq = detailSequence;
  detailController = new AbortController();
  detailLoading.value = true;
  detailRows.value = [];
  detailCount.value = 0;
  detailError.value = '';
  detailPage.value = next;
  try {
    const data = await fetchRows({ ...detailParams, offset: (next - 1) * 20 }, detailController.signal);
    if (seq !== detailSequence) return;
    detailRows.value = data.results;
    detailCount.value = data.count;
  } catch (err) {
    if (seq === detailSequence) detailError.value = err.message;
  } finally {
    if (seq === detailSequence) detailLoading.value = false;
  }
}
onMounted(async () => {
  try {
    countries.value = (await fetchRows({})).countries;
    if (countries.value.length === 1) country.value = countries.value[0].id;
  } catch (err) {
    error.value = err.message;
  }
});
onUnmounted(reset);
</script>

<style scoped>
.navigation, .metrics { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 14px 0; }
.metrics > div { flex: 1; min-width: 130px; border: 1px solid var(--el-border-color-light); border-radius: 8px; padding: 14px 18px; background: white; }
.metrics strong { display: block; font-size: 22px; margin-top: 6px; }
small { display: block; }
small, .note { color: var(--el-text-color-secondary); }
.el-pagination { margin-top: 14px; }
</style>
