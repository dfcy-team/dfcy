<template>
  <section>
    <h2>出入库明细</h2>
    <p>日期按仓库当地时间计算。出库覆盖已同步且有明确发货记录的仓库单。</p>
    <el-radio-group v-model="direction" @change="search">
      <el-radio-button value="all">全部</el-radio-button>
      <el-radio-button value="inbound">入库</el-radio-button>
      <el-radio-button value="outbound">出库</el-radio-button>
    </el-radio-group>
    <el-form inline @submit.prevent="search">
      <el-form-item label="国家">
        <el-select v-model="filters.site_code" clearable placeholder="全部" style="width: 140px">
          <el-option label="菲律宾" value="PH" />
          <el-option label="泰国" value="TH" />
          <el-option label="马来西亚" value="MY" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库"><el-input v-model.trim="filters.warehouse" placeholder="仓库名称或编码" clearable /></el-form-item>
      <el-form-item label="业务日期">
        <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
      </el-form-item>
      <el-form-item label="SKU 或单号"><el-input v-model.trim="filters.search" clearable /></el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
        <el-button v-if="direction !== 'all'" :disabled="!result.total || loading" :loading="exporting" @click="exportRows(direction)">导出{{ label }}明细</el-button>
      </el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div v-if="!loading && !error && !tracedDocument">
      <p v-for="entry in coverageEntries" :key="entry.label">
        {{ entry.label }}已同步记录日期：
        {{ entry.coverage?.map(range => `${range.site_code} ${range.first_date} 至 ${range.last_date}`).join('；') || '暂无记录' }}
        <span v-if="outsideCoverage(entry.coverage)"> · 所选期间超出已观察日期范围</span>
      </p>
    </div>
    <template v-if="direction === 'all'">
      <div v-loading="loading">
        <p v-for="entry in summaries" :key="entry.direction">
          {{ entry.label }} {{ entry.quantity.toLocaleString() }} 件，共 {{ entry.total }} 行 ·
          {{ entry.latest_at ? '区间内最近业务时间 ' + entry.latest_at : '区间内暂无符合条件的同步记录' }}
          <el-button link type="primary" @click="showDetails(entry.direction)">查看明细</el-button>
          <el-button link type="primary" :disabled="!entry.total || exporting" @click="exportRows(entry.direction)">导出</el-button>
        </p>
      </div>
    </template>
    <template v-else>
    <p v-if="tracedDocument">
      来源单据 {{ tracedDocument }}
      <el-button link type="primary" @click="returnToPeriod">返回期间查询</el-button>
    </p>
    <p>{{ label }} {{ quantity.toLocaleString() }} 件，共 {{ result.total }} 行</p>
    <el-table v-loading="loading" :data="result.items" row-key="id">
      <el-table-column prop="site_code" label="国家" width="90" />
      <el-table-column prop="warehouse_name" label="仓库" />
      <el-table-column :label="isOutbound ? '实际发货时间' : '实际收货时间'" min-width="215">
        <template #default="{ row }">{{ (row.shipped_at_local || row.received_at_local).replace('T', ' ').replace(/\.\d+/, '') }}</template>
      </el-table-column>
      <el-table-column :label="isOutbound ? '仓库单号' : '入库单号'" min-width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="traceDocument(row)">{{ row.document || row.external_inbound_id }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="source_sku" label="来源 SKU" />
      <el-table-column :prop="isOutbound ? 'warehouse_sku' : 'internal_sku'" :label="isOutbound ? '仓库 SKU' : '内部 SKU'" />
      <el-table-column :prop="isOutbound ? 'quantity' : 'received_quantity'" label="件数" align="right" />
    </el-table>
    <el-pagination :current-page="page" :page-size="20" :total="result.total" layout="prev, pager, next" @current-change="load" />
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { downloadApiFile, formatApiError, requestApi } from '../../api/request';

const endpoint = '/api/internal/supply-chain/v2/wms-inbound-movements/';
const filters = reactive({ site_code: '', warehouse: '', search: '' });
const dates = ref(null);
const direction = ref('inbound');
const isOutbound = computed(() => direction.value === 'outbound');
const label = computed(() => isOutbound.value ? '出库' : '入库');
const empty = () => ({ items: [], total: 0, received_quantity: 0 });
const result = ref(empty());
const summaries = ref([]);
const coverageEntries = computed(() => direction.value === 'all' ? summaries.value : [{ label: label.value, coverage: result.value.coverage }]);
const tracedDocument = ref('');
const quantity = computed(() => result.value.quantity ?? result.value.received_quantity ?? 0);
const page = ref(1);
const loading = ref(false);
const exporting = ref(false);
const error = ref('');
let applied = {};
let periodQuery = {};
let controller;

function outsideCoverage(coverage) {
  if (!coverage?.length) return false;
  return coverage.some(range => (applied.start_date && applied.start_date < range.first_date)
    || (applied.end_date && applied.end_date > range.last_date));
}

async function load(nextPage) {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  page.value = nextPage;
  loading.value = true;
  error.value = '';
  try {
    const fetchDirection = async (mode) => {
      const response = await requestApi({ method: 'get', url: endpoint, params: { ...applied, direction: mode, page: nextPage }, signal: request.signal });
      if (response.success === false) throw new Error(formatApiError(response));
      return response.data;
    };
    if (applied.direction === 'all') {
      const [inbound, outbound] = await Promise.all([fetchDirection('inbound'), fetchDirection('outbound')]);
      if (request.signal.aborted) return;
      summaries.value = [
        { ...inbound, direction: 'inbound', label: '入库', quantity: inbound.received_quantity },
        { ...outbound, direction: 'outbound', label: '出库' },
      ];
      return;
    }
    const data = await fetchDirection(applied.direction);
    if (request.signal.aborted) return;
    result.value = data;
  } catch (err) {
    if (request.signal.aborted) return;
    result.value = empty();
    error.value = err.message || '查询失败，请重试。';
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}

function search() {
  const [start_date, end_date] = dates.value || [];
  applied = Object.fromEntries(Object.entries({ ...filters, direction: direction.value, start_date, end_date }).filter(([, value]) => value));
  result.value = empty();
  summaries.value = [];
  tracedDocument.value = '';
  return load(1);
}

function traceDocument(row) {
  if (!tracedDocument.value) periodQuery = applied;
  tracedDocument.value = row.document || row.external_inbound_id;
  applied = { direction: direction.value, site_code: row.site_code, warehouse_id: row.warehouse, document: tracedDocument.value };
  return load(1);
}

function returnToPeriod() {
  tracedDocument.value = '';
  applied = periodQuery;
  return load(1);
}

function showDetails(mode) {
  direction.value = mode;
  applied = { ...applied, direction: mode };
  return load(1);
}

async function exportRows(mode) {
  exporting.value = true;
  error.value = '';
  try {
    const response = await downloadApiFile(`${endpoint}?${new URLSearchParams({ ...applied, direction: mode, export: 'csv' })}`,
      mode === 'outbound' ? '出库明细.csv' : '入库明细.csv');
    if (!response.success) throw new Error(formatApiError(response));
  } catch (err) {
    error.value = err.message || '导出失败，请重试。';
  } finally {
    exporting.value = false;
  }
}

onMounted(search);
onBeforeUnmount(() => controller?.abort());
</script>
