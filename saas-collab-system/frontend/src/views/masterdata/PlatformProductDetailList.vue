<template>
  <AppPage
    eyebrow="MASTER DATA"
    title="平台商品明细"
    subtitle="按平台、店铺维护商品与变体快照；旧 SKU 关联仅用于内部 SKU 映射，不保存平台凭据。"
    boundary-note="页面只展示当前 tenant 可见的商品明细；导入会校验平台、店铺、国家代码和旧 SKU 的租户边界。"
    :capability="capability"
  >
    <template #action>
      <el-button class="template-button" @click="downloadTemplate">下载导入模板</el-button>
      <el-button class="format-button" @click="templateDialog = true">字段说明</el-button>
      <el-button class="import-button" type="primary" :loading="importing" :disabled="importing" @click="fileInput?.click()">{{ importing ? '正在导入' : '导入 CSV/XLSX' }}</el-button>
      <input ref="fileInput" hidden type="file" accept=".csv,.xlsx" @change="onImport" />
    </template>

    <el-alert
      v-if="message"
      class="page-message"
      :title="message"
      :type="messageType"
      show-icon
      closable
      @close="message = ''"
    />

    <section class="resource-summary" aria-label="数据摘要">
      <div class="summary-item">
        <span>当前结果</span>
        <strong>{{ total }}</strong>
      </div>
      <div class="summary-item">
        <span>已关联新 SKU</span>
        <strong>{{ linkedCount }}</strong>
      </div>
      <div class="summary-item">
        <span>在售明细</span>
        <strong>{{ onSaleCount }}</strong>
      </div>
      <div class="summary-item summary-item--scope">
        <span>数据边界</span>
        <strong>当前 tenant</strong>
      </div>
    </section>

    <section class="resource-toolbar" aria-label="筛选条件">
      <el-input
        v-model="filters.search"
        clearable
        placeholder="搜索标题、平台 SKU 或旧 SKU"
        @keyup.enter="loadData"
      />
      <el-select v-model="filters.platform_id" clearable filterable placeholder="全部平台">
        <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.store_id" clearable filterable placeholder="全部店铺">
        <el-option v-for="item in storeOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.sales_status" clearable placeholder="全部销售状态">
        <el-option label="在售" value="在售" />
        <el-option label="停售" value="停售" />
        <el-option label="草稿" value="草稿" />
      </el-select>
      <div class="toolbar-actions">
        <el-button type="primary" @click="loadData">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </section>

    <AppState
      v-if="pageState !== 'ready' && pageState !== 'empty'"
      :status="pageState"
      :title="stateTitle"
      :detail="stateDetail"
      @action="loadData"
    />

    <section v-else class="resource-table" aria-label="平台商品明细列表">
      <el-table :data="rows" border table-layout="fixed" empty-text="暂无符合条件的平台商品明细">
        <el-table-column prop="platform_name" label="平台" min-width="130" show-overflow-tooltip />
        <el-table-column prop="country_code" label="国家代码" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.country_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="store_name" label="店铺" min-width="140" show-overflow-tooltip />
        <el-table-column prop="platform_product_id" label="平台商品 ID" min-width="150" show-overflow-tooltip />
        <el-table-column prop="platform_variant_id" label="变体 ID" min-width="140" show-overflow-tooltip />
        <el-table-column prop="platform_sku" label="平台 SKU" min-width="140" show-overflow-tooltip />
        <el-table-column prop="source_old_sku_code" label="旧 SKU 关联" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_old_sku_code || row.internal_legacy_sku_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="internal_sku_code" label="新 SKU" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.internal_sku_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="190" show-overflow-tooltip />
        <el-table-column prop="variant" label="变体" min-width="150" show-overflow-tooltip />
        <el-table-column prop="sales_status" label="销售状态" min-width="110">
          <template #default="{ row }">
            <el-tag :type="salesStatusType(row.sales_status)" effect="plain">
              {{ row.sales_status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="负责人" min-width="110" show-overflow-tooltip />
        <el-table-column prop="leader" label="组长" min-width="110" show-overflow-tooltip />
      </el-table>

      <footer class="resource-pagination">
        <span>共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          :page-size="filters.page_size"
          :total="total"
          layout="prev, pager, next"
          @current-change="handlePageChange"
        />
      </footer>
    </section>

    <el-dialog v-model="importDialog" :title="importing ? '正在导入' : '导入结果'" width="min(680px, 94vw)" :close-on-click-modal="!importing" :show-close="!importing">
      <el-steps :active="importStep" finish-status="success" align-center><el-step title="文件已选择"/><el-step title="上传并解析"/><el-step title="导入完成"/></el-steps>
      <div class="import-status" v-loading="importing"><p><strong>{{ importStatus }}</strong></p><p class="import-meta">文件：{{ importFileName || '-' }} · 已用时 {{ importElapsedSeconds }} 秒</p><pre v-if="importResult" class="result">{{ JSON.stringify(importResult, null, 2) }}</pre></div>
      <template #footer><el-button :disabled="importing" @click="importDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="templateDialog" title="导入模板与字段说明" width="min(920px, 94vw)">
      <p class="template-help">
        请先下载 CSV 模板并按首行字段填写；系统同时接受 Excel 另存的 XLSX 文件。必填字段为空、平台/店铺/国家代码不属于当前租户，或旧 SKU 无法匹配时，该行会被拒绝且不会写入其他行。
      </p>
      <el-table :data="importFields" border size="small" class="template-fields">
        <el-table-column prop="field" label="字段" min-width="140" />
        <el-table-column prop="required" label="必填" width="70" />
        <el-table-column prop="description" label="填写说明" min-width="360" show-overflow-tooltip />
        <el-table-column prop="example" label="示例" min-width="150" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="templateDialog = false">关闭</el-button>
        <el-button type="primary" @click="downloadTemplate">再次下载 CSV 模板</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPlatforms, fetchStores } from '../../api/masterData';
import { fetchPlatformProductDetails, importPlatformProductDetails } from '../../api/platformProductDetails';
import { useMock } from '../../api/request';
import { statusFromApiResponse } from '../../utils/uiState';

const fileInput = ref(null);
const rows = ref([]);
const allRows = ref([]);
const total = ref(0);
const loading = ref(false);
const pageState = ref('loading');
const stateTitle = ref('');
const stateDetail = ref('');
const capability = ref(useMock ? 'mock' : 'pending');
const message = ref('');
const messageType = ref('success');
const importDialog = ref(false);
const templateDialog = ref(false);
const importResult = ref(null);
const importing = ref(false), importStep = ref(0), importStatus = ref('等待选择文件'), importFileName = ref(''), importElapsedSeconds = ref(0);
let importTimer = null;
const serverPaginated = ref(false);
const platformOptions = ref([]);
const storeOptions = ref([]);
const filters = reactive({ search: '', platform_id: '', store_id: '', sales_status: '', page: 1, page_size: 20 });

const importFields = [
  { field: '平台', required: '是', description: '平台编码、名称或平台类型；必须属于当前租户。', example: 'tiktok' },
  { field: '店铺', required: '是', description: '店铺编码或名称；必须属于所选平台和当前租户。', example: 'shop-th' },
  { field: '国家代码', required: '否', description: 'CountrySiteMaster.country_code（如 TH）；填写时必须与店铺国家一致，并匹配当前租户的国家档案。', example: 'TH' },
  { field: '平台商品ID', required: '否', description: '平台商品（SPU）标识。', example: 'P-1001' },
  { field: '变体ID', required: '是', description: '平台变体标识；同一租户的平台+店铺内用于幂等更新。', example: 'V-1001' },
  { field: '平台SKU', required: '否', description: '平台侧 SKU 标识。', example: 'TSHIRT-BLACK-M' },
  { field: '旧SKU编码', required: '二选一', description: '与新SKU编码至少填写一个；用于匹配旧 SKU 迁移关系。', example: 'OLD-SKU-001' },
  { field: '新SKU编码', required: '二选一', description: '与旧SKU编码至少填写一个；两者都填时优先使用新 SKU。', example: '101010004-blue' },
  { field: '标题', required: '否', description: '平台商品标题。', example: 'Basic T-shirt' },
  { field: '变体', required: '否', description: '颜色、尺码等变体描述。', example: 'Black / M' },
  { field: 'L1类目 / L2类目 / L3类目', required: '否', description: '平台类目层级，可留空。', example: '服饰 / 上衣 / T恤' },
  { field: 'SKU前缀', required: '否', description: '内部业务使用的 SKU 前缀。', example: 'APP' },
  { field: '销售状态', required: '否', description: '在售、停售、草稿等状态文本。', example: '在售' },
  { field: '负责人 / 组长', required: '否', description: '店铺负责人及组长文本。', example: '张三 / 李四' },
  { field: '平台创建时间 / 平台更新时间', required: '否', description: '支持 ISO 或 YYYY-MM-DD[ HH:mm:ss] 格式。', example: '2026-08-13 10:00:00' },
];

const templateHeaders = [
  '平台', '店铺', '国家代码', '平台商品ID', '变体ID', '平台SKU', '旧SKU编码', '新SKU编码', '标题', '变体',
  'L1类目', 'L2类目', 'L3类目', 'SKU前缀', '销售状态', '负责人', '组长', '平台创建时间', '平台更新时间',
];
const templateExample = [
  'tiktok', 'shop-th', 'TH', 'P-1001', 'V-1001', 'TSHIRT-BLACK-M', '', '101010004-blue',
  'Basic T-shirt', 'Black / M', '服饰', '上衣', 'T恤', 'APP', '在售', '张三', '李四', '2026-08-13 10:00:00', '2026-08-13 10:00:00',
];

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadTemplate() {
  const csv = `\ufeff${templateHeaders.map(csvCell).join(',')}\r\n${templateExample.map(csvCell).join(',')}\r\n`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '平台商品明细导入模板.csv';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const linkedCount = computed(() => allRows.value.filter((row) => row.internal_sku_code || row.internal_sku).length);
const onSaleCount = computed(() => allRows.value.filter((row) => /active|on.?sale|在售/i.test(String(row.sales_status || ''))).length);

function responseRows(response) {
  const data = response?.data;
  if (Array.isArray(data)) return { results: data, count: data.length, paginated: false, apiStatus: response?.api_status };
  const results = Array.isArray(data?.results) ? data.results : (Array.isArray(data?.items) ? data.items : []);
  return {
    results,
    count: Number.isFinite(Number(data?.count)) ? Number(data.count) : results.length,
    paginated: Array.isArray(data?.results) && ('next' in data || 'previous' in data),
    apiStatus: data?.api_status || response?.api_status,
  };
}

function applyRows(results) {
  allRows.value = results;
  if (serverPaginated.value) rows.value = results;
  else {
    const start = (filters.page - 1) * filters.page_size;
    rows.value = results.slice(start, start + filters.page_size);
  }
}

async function loadData() {
  loading.value = true;
  pageState.value = 'loading';
  stateTitle.value = '';
  stateDetail.value = '';
  const response = await fetchPlatformProductDetails({ ...filters, status: filters.sales_status });
  loading.value = false;
  if (!response?.success) {
    pageState.value = statusFromApiResponse(response, typeof navigator === 'undefined' ? true : navigator.onLine);
    stateTitle.value = '平台商品明细加载失败';
    stateDetail.value = response?.message || '接口请求失败';
    capability.value = response?.http_status ? 'pending' : 'degraded';
    return;
  }
  const payload = responseRows(response);
  serverPaginated.value = payload.paginated;
  total.value = payload.count;
  applyRows(payload.results);
  capability.value = payload.apiStatus || (useMock ? 'mock' : 'connected');
  pageState.value = payload.results.length ? 'ready' : 'empty';
}

function handlePageChange(page) {
  filters.page = page;
  if (serverPaginated.value) loadData();
  else applyRows(allRows.value);
}

function resetFilters() {
  filters.search = '';
  filters.platform_id = '';
  filters.store_id = '';
  filters.sales_status = '';
  filters.page = 1;
  loadData();
}

function salesStatusType(value) {
  if (/active|on.?sale|在售/i.test(String(value || ''))) return 'success';
  if (/inactive|off.?sale|停售/i.test(String(value || ''))) return 'info';
  if (/draft|草稿/i.test(String(value || ''))) return 'warning';
  return 'info';
}

function optionRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (Array.isArray(data?.results) ? data.results : []);
}

async function loadReferenceOptions() {
  const [platformResponse, storeResponse] = await Promise.all([
    fetchPlatforms({ page: 1, page_size: 100, status: 'active' }),
    fetchStores({ page: 1, page_size: 100, status: 'active' }),
  ]);
  platformOptions.value = optionRows(platformResponse).map((item) => ({
    label: `${item.name || item.code} · ${item.code || item.id}`,
    value: item.id,
  }));
  storeOptions.value = optionRows(storeResponse).map((item) => ({
    label: `${item.name || item.code} · ${item.code || item.id}`,
    value: item.id,
  }));
}

async function onImport(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  importDialog.value = true;
  importing.value = true; importStep.value = 1; importStatus.value = '正在上传文件，服务器正在解析并校验数据，请勿关闭页面。'; importFileName.value = file.name; importElapsedSeconds.value = 0; importResult.value = null;
  const startedAt = Date.now(); clearInterval(importTimer); importTimer = setInterval(() => { importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); }, 1000);
  try {
    const response = await importPlatformProductDetails(file, { dryRun: false });
    importResult.value = response?.data || response;
    if (response?.success) { importStep.value = 3; importStatus.value = '导入完成，列表数据已刷新。'; message.value = '导入完成'; messageType.value = 'success'; filters.page = 1; await loadData(); }
    else { importStatus.value = response?.message || '导入失败，请根据结果信息修正文件后重试。'; message.value = importStatus.value; messageType.value = 'error'; }
  } finally { importing.value = false; importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); clearInterval(importTimer); importTimer = null; }
}

onMounted(async () => {
  await loadReferenceOptions();
  await loadData();
});
onUnmounted(() => clearInterval(importTimer));
</script>

<style scoped>
.page-message { margin-bottom: 16px; }
.template-button, .format-button, .import-button { min-width: 116px; height: 36px; padding: 0 14px; }
.import-button { min-width: 144px; }
.template-help { margin: 0 0 14px; color: #475569; line-height: 1.6; }
.template-fields :deep(.cell) { line-height: 1.45; }
.resource-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(112px, 160px)) minmax(180px, 1fr);
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}
.summary-item { min-height: 74px; padding: 14px 16px; border-right: 1px solid #e5eaf0; }
.summary-item:last-child { border-right: 0; }
.summary-item span { display: block; color: #64748b; font-size: 12px; }
.summary-item strong { display: block; margin-top: 8px; color: #172033; font-size: 20px; }
.summary-item--scope strong { font-size: 15px; }
.resource-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 170px 190px 160px auto;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid #dbe3ec;
  background: #fff;
}
.toolbar-actions { display: flex; gap: 8px; }
.resource-table { min-width: 0; margin-top: 16px; overflow: hidden; }
.resource-table :deep(.el-table) { width: 100%; }
.resource-pagination { display: flex; align-items: center; justify-content: space-between; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.result { max-height: 420px; overflow: auto; white-space: pre-wrap; }
.import-status { min-height: 130px; margin-top: 24px; padding: 16px; border-radius: 8px; background: #f8fafc; }
.import-status p { margin: 0 0 8px; }
.import-meta { color: #64748b; font-size: 13px; }
@media (max-width: 960px) {
  .resource-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n + 2) { border-bottom: 1px solid #e5eaf0; }
  .resource-toolbar { grid-template-columns: 1fr 1fr; }
  .resource-toolbar > .el-input { grid-column: 1 / -1; }
  .toolbar-actions { justify-content: flex-end; }
}
</style>
