<script setup>
import { reactive, ref } from 'vue';
import { fetchWmsInboundDocument, fetchWmsInboundDocuments } from '../../api/supplyLogisticsV2';

defineProps({ active: Boolean });
const emit = defineEmits(['open-inbound']);
const filters = reactive({ search: '', warehouse: '', start_date: '', end_date: '' });
const items = ref([]), total = ref(0), page = ref(1);
const loading = ref(false), error = ref('');
const detail = ref(null), detailOpen = ref(false), detailLoading = ref(false), detailError = ref('');
let listRequest = 0;
let detailRequest = 0;

function unwrap(response) {
  if (!response?.success) throw new Error(response?.message || '请求失败');
  return response.data;
}
async function load(nextPage = 1) {
  const request = ++listRequest;
  page.value = nextPage;
  loading.value = true;
  error.value = '';
  try {
    const data = unwrap(await fetchWmsInboundDocuments({ ...filters, page: nextPage }));
    if (request !== listRequest) return;
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    if (request !== listRequest) return;
    items.value = [];
    total.value = 0;
    error.value = e.message || '加载三方仓入库单失败';
  } finally {
    if (request === listRequest) loading.value = false;
  }
}
async function open(id) {
  const request = ++detailRequest;
  detail.value = null;
  detailError.value = '';
  detailOpen.value = true;
  detailLoading.value = true;
  try {
    const data = unwrap(await fetchWmsInboundDocument(id));
    if (request === detailRequest) detail.value = data;
  } catch (e) {
    if (request === detailRequest) detailError.value = e.message || '加载三方仓明细失败';
  } finally {
    if (request === detailRequest) detailLoading.value = false;
  }
}
function openInbound(doc) {
  detailOpen.value = false;
  emit('open-inbound', doc);
}
const displayTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
defineExpose({ open, load });
</script>

<template>
  <section v-if="active" class="wms-documents">
    <form class="wms-filters" @submit.prevent="load()">
      <el-input v-model="filters.search" clearable placeholder="三方仓单号 / 新旧 SKU" aria-label="三方仓单号或 SKU"/>
      <el-input v-model="filters.warehouse" clearable placeholder="仓库名称 / 编码" aria-label="仓库名称或编码"/>
      <el-date-picker v-model="filters.start_date" type="date" value-format="YYYY-MM-DD" placeholder="入库开始日期"/>
      <el-date-picker v-model="filters.end_date" type="date" value-format="YYYY-MM-DD" placeholder="入库结束日期"/>
      <el-button native-type="submit" :loading="loading">查询</el-button>
    </form>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-table v-loading="loading" :data="items" border empty-text="暂无三方仓入库单">
      <el-table-column label="三方仓单号" min-width="180"><template #default="{row}">
        <el-button link type="primary" @click="open(row.id)">{{ row.external_inbound_id }}</el-button>
      </template></el-table-column>
      <el-table-column prop="site_code" label="国家" width="90"/>
      <el-table-column prop="warehouse__name" label="仓库" min-width="140"/>
      <el-table-column label="入库时间" min-width="170"><template #default="{row}">{{ displayTime(row.received_at) }}</template></el-table-column>
      <el-table-column prop="received_quantity" label="实收件数" width="100"/>
      <el-table-column label="本系统入库单" min-width="180"><template #default="{row}">
        <el-button v-for="doc in row.inbounds" :key="doc.id" link type="primary" @click="openInbound(doc)">{{ doc.number }}</el-button>
        <span v-if="!row.inbounds.length">—</span>
      </template></el-table-column>
    </el-table>
    <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="20"
      :current-page="page" @current-change="load"/>
  </section>
  <el-dialog v-model="detailOpen" append-to-body :title="detail?.external_inbound_id || '三方仓入库单'" width="min(1000px, 96vw)">
    <el-alert v-if="detailError" :title="detailError" type="error" :closable="false"/>
    <div v-loading="detailLoading" class="wms-detail">
      <template v-if="detail">
        <p>{{ detail.site_code }} · {{ detail.warehouse__name }}</p>
        <div v-if="detail.inbounds.length">
          关联入库单
          <el-button v-for="doc in detail.inbounds" :key="doc.id" type="primary" link @click="openInbound(doc)">{{ doc.number }}</el-button>
        </div>
        <el-table :data="detail.lines" border max-height="520">
          <el-table-column prop="internal_sku__product_name" label="商品" min-width="155"/>
          <el-table-column prop="source_sku" label="仓库回传 SKU" min-width="145"/>
          <el-table-column prop="internal_sku__sku_code" label="新 SKU" min-width="125"/>
          <el-table-column prop="internal_sku__legacy_sku_code" label="旧 SKU" min-width="125"/>
          <el-table-column prop="planned_quantity" label="计划数量" width="90"/>
          <el-table-column prop="received_quantity" label="实收数量" width="90"/>
          <el-table-column prop="status" label="回传状态" min-width="100"/>
        </el-table>
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.wms-filters { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 18px; }
.wms-filters :deep(.el-input) { width: min(220px, 100%); }
.wms-detail { min-height: 64px; }
</style>
