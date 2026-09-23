<template>
  <section class="cost-page">
    <header class="page-header">
      <div>
        <h1>商品成本</h1>
        <p>按仓库所在地和生效期间维护 SKU 成本版本；同一 SKU 在不同仓库可采用不同成本，历史成本永久保留。采购价格仅作为成本构成项。</p>
      </div>
      <div class="header-actions">
        <el-button @click="load">刷新</el-button>
        <el-button v-if="canImport" data-testid="cost-import-button" @click="openImport">每期成本导入</el-button>
        <el-button v-if="canBackfill" type="primary" data-testid="cost-backfill-button" @click="openBackfill">系统生成回填</el-button>
      </div>
    </header>

    <el-alert
      class="definition-alert"
      title="成本口径：商品成本 = 采购价格 + 物流分摊 + 税费 + 包装费 + 其他费用。调整成本只新增版本，不覆盖历史；下游业务须按仓库和发生时间锁定成本快照。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="summary-strip" aria-label="成本核对概览">
      <div><span>SKU × 仓库</span><strong>{{ visibleRows.length }}</strong><small>当前查询范围</small></div>
      <div><span>待核对</span><strong class="warning">{{ statusCount('pending') }}</strong><small>系统生成未确认</small></div>
      <div><span>存在差异</span><strong class="danger">{{ statusCount('difference') }}</strong><small>需人工判断</small></div>
      <div><span>已确认</span><strong class="success">{{ statusCount('confirmed') }}</strong><small>已生效成本</small></div>
    </div>

    <div class="content-panel">
      <el-form class="filters" inline @submit.prevent="applyFilters">
        <el-form-item label="商品 / SKU">
          <el-input v-model="filters.search" clearable placeholder="输入商品名称、SPU 或 SKU" @keyup.enter="applyFilters" />
        </el-form-item>
        <el-form-item label="核对状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态">
            <el-option label="待核对" value="pending" />
            <el-option label="存在差异" value="difference" />
            <el-option label="已确认" value="confirmed" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库所在地">
          <el-select v-model="filters.warehouse" clearable placeholder="全部仓库 / 国家" filterable style="width:220px">
            <el-option v-for="warehouse in warehouses" :key="warehouse.id" :label="`${warehouse.name}（${warehouse.country_code}）`" :value="warehouse.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilters">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="visibleRows" row-key="id" border empty-text="暂无商品成本数据">
        <el-table-column prop="sku_code" label="SKU" min-width="170" fixed="left">
          <template #default="{ row }"><code>{{ row.sku_code }}</code></template>
        </el-table-column>
        <el-table-column prop="product_name" label="商品名称" min-width="210" show-overflow-tooltip />
        <el-table-column label="仓库 / 所在国家" min-width="180"><template #default="{ row }">{{ row.warehouse_name || row.warehouse_code || '未归属仓库（历史）' }}<small v-if="row.warehouse_country_code"> · {{ row.warehouse_country_code }}</small></template></el-table-column>
        <el-table-column label="采购价格" min-width="110" align="right">
          <template #default="{ row }">{{ money(row.purchase_price) }}</template>
        </el-table-column>
        <el-table-column label="附加费用" min-width="110" align="right">
          <template #default="{ row }">{{ money(extraCost(row)) }}</template>
        </el-table-column>
        <el-table-column label="系统成本" min-width="115" align="right">
          <template #default="{ row }"><span class="system-cost">{{ money(row.system_cost) }}</span></template>
        </el-table-column>
        <el-table-column label="已确认商品成本" min-width="145" align="right">
          <template #default="{ row }"><strong>{{ money(row.confirmed_cost) }}</strong></template>
        </el-table-column>
        <el-table-column label="差异" min-width="100" align="right">
          <template #default="{ row }"><span :class="differenceClass(row)">{{ difference(row) }}</span></template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">{{ row.source === 'manual' ? '人工维护' : '系统生成' }}</template>
        </el-table-column>
        <el-table-column label="核对状态" width="110">
          <template #default="{ row }"><el-tag :type="statusMeta[row.status].type">{{ statusMeta[row.status].label }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="version_no" label="当前版本" width="95" />
        <el-table-column prop="effective_date" label="生效日期" width="115">
          <template #default="{ row }">{{ row.effective_date || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="inspect(row)">查看构成</el-button>
            <el-button link type="primary" @click="showHistory(row)">历史版本</el-button>
            <el-button v-if="canManage && row.warehouse" link type="primary" @click="edit(row)">维护</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" :title="drawerReadonly ? '成本构成' : '维护商品成本'" size="480px">
      <div class="sku-heading">
        <code>{{ form.sku_code }}</code>
        <strong>{{ form.product_name }}</strong>
        <span>{{ form.warehouse_name || form.warehouse_code || '未归属仓库（历史）' }} · {{ form.warehouse_country_code || '-' }}</span>
      </div>
      <div v-if="!drawerReadonly" class="change-preview" data-testid="cost-change-preview">
        <div><span>当前生效成本</span><strong>{{ money(form.original_confirmed_cost) }}</strong><small>{{ form.version_no || '暂无版本' }}</small></div>
        <div class="change-arrow">→</div>
        <div><span>拟生效成本</span><strong>{{ money(form.confirmed_cost) }}</strong><small>保存后新增版本</small></div>
        <div class="change-result"><span>成本变化</span><strong :class="changeAmount === 0 ? 'muted' : 'difference-value'">{{ signedMoney(changeAmount) }}</strong><small>{{ changeRate }}</small></div>
      </div>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="采购价格"><el-input v-model="form.purchase_price" :disabled="drawerReadonly" /></el-form-item>
          <el-form-item label="物流分摊"><el-input v-model="form.freight_cost" :disabled="drawerReadonly" /></el-form-item>
          <el-form-item label="税费"><el-input v-model="form.duty_cost" :disabled="drawerReadonly" /></el-form-item>
          <el-form-item label="包装费"><el-input v-model="form.packaging_cost" :disabled="drawerReadonly" /></el-form-item>
          <el-form-item label="其他费用"><el-input v-model="form.other_cost" :disabled="drawerReadonly" /></el-form-item>
          <el-form-item label="系统成本"><el-input :model-value="calculatedFormCost" disabled /></el-form-item>
        </div>
        <el-form-item label="确认采用的商品成本">
          <el-input v-model="form.confirmed_cost" :disabled="drawerReadonly" placeholder="填写后作为下游业务生效成本" />
        </el-form-item>
        <el-form-item v-if="!drawerReadonly && form.status !== 'pending'" label="新版本生效日期" required>
          <el-date-picker v-model="form.effective_from" type="date" value-format="YYYY-MM-DD" placeholder="选择生效日期" style="width:100%" />
        </el-form-item>
        <el-form-item v-if="!drawerReadonly" label="调整原因" required>
          <el-input v-model="form.reason" type="textarea" :rows="3" placeholder="说明人工调整或确认系统成本的原因" />
        </el-form-item>
      </el-form>
      <div class="audit-note">最近更新：{{ form.updated_by || '-' }} · {{ form.updated_at || '-' }}</div>
      <template #footer>
        <el-button @click="drawerVisible = false">关闭</el-button>
        <el-button v-if="!drawerReadonly" @click="adoptSystemCost">采用系统成本</el-button>
        <el-button v-if="!drawerReadonly" type="primary" :loading="saving" @click="save">新增版本并确认</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="backfillVisible" title="系统生成回填" width="min(640px, 94vw)">
      <div class="backfill-flow">
        <div><b>1</b><span>读取采购价格</span></div><i>→</i><div><b>2</b><span>分摊物流与费用</span></div><i>→</i><div><b>3</b><span>生成待核对成本</span></div>
      </div>
      <el-alert title="回填不会覆盖或改写任何历史成本；每次结果都生成新的待核对版本，确认后才按生效日期接续当前版本。" type="warning" :closable="false" />
      <el-form label-position="top" class="backfill-form">
        <el-form-item label="回填范围"><el-radio-group v-model="backfill.scope"><el-radio value="all">全部 SKU</el-radio><el-radio value="pending">仅未确认 SKU</el-radio></el-radio-group></el-form-item>
        <el-form-item label="仓库所在地" required><el-select v-model="backfill.warehouse" filterable placeholder="请选择仓库"><el-option v-for="warehouse in warehouses" :key="warehouse.id" :label="`${warehouse.name}（${warehouse.country_code}）`" :value="warehouse.id" /></el-select></el-form-item>
        <el-form-item label="费用口径"><el-select v-model="backfill.rule"><el-option label="最新入库批次加权成本" value="latest" /><el-option label="近 30 天移动加权成本" value="moving30" /></el-select></el-form-item>
        <el-form-item label="拟生效日期"><el-date-picker v-model="backfill.effective_from" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
      </el-form>
      <div v-if="preview" class="preview-result"><strong>预览结果</strong><span>该仓库匹配 {{ preview.matched }} 个 SKU，预计更新 {{ preview.changed }} 个，保持不变 {{ preview.unchanged }} 个。</span></div>
      <template #footer>
        <el-button @click="backfillVisible = false">取消</el-button>
        <el-button type="primary" :loading="previewing" data-testid="cost-backfill-preview" @click="previewBackfill">生成预览</el-button>
        <el-button v-if="preview" type="success" :loading="previewing" data-testid="cost-backfill-execute" @click="executeBackfill">写入待核对版本</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="成本历史版本" width="min(720px, 94vw)">
      <p class="history-note">{{ historySku }} · {{ historyWarehouse }} · 已结束版本仍用于还原历史订单、利润及经营报表。</p>
      <el-table :data="historyRows" border empty-text="暂无已生效历史版本">
        <el-table-column prop="version_no" label="版本" width="90" />
        <el-table-column label="商品成本" width="130"><template #default="{ row }">{{ money(row.cost) }}</template></el-table-column>
        <el-table-column prop="effective_from" label="生效开始" width="120" />
        <el-table-column label="生效结束" width="120"><template #default="{ row }">{{ row.effective_to || '当前生效' }}</template></el-table-column>
        <el-table-column prop="source" label="来源" />
      </el-table>
    </el-dialog>

    <el-dialog v-model="importVisible" title="每期商品成本导入" width="min(720px, 94vw)" @closed="resetImport">
      <el-alert title="支持 CSV / XLSX。每行指定仓库编码，按仓库所在地核算成本；导入只追加版本，须先预检再确认。" type="info" :closable="false" />
      <div class="template-guide">
        <div><strong>第一步：下载模板</strong><span>模板已包含中文列名，按表格填写即可。</span></div>
        <el-button type="primary" plain data-testid="cost-template-download" @click="downloadImportTemplate">下载导入模板</el-button>
      </div>
      <div class="import-tips">
        <strong>第二步：填写并上传</strong>
        <span>SKU编码和旧SKU编码二选一；仓库编码从仓库档案填写，系统按该仓库所在国家归属成本。其余带 * 的列为必填项。</span>
      </div>
      <el-upload drag :auto-upload="false" :limit="1" accept=".csv,.xlsx" :on-change="selectImportFile" :on-remove="resetImportFile">
        <div><strong>上传已填写的成本模板</strong><small>拖入文件，或点击选择 CSV / XLSX</small></div>
      </el-upload>
      <div v-if="importing || importProgress" class="import-progress" data-testid="cost-import-progress">
        <div><strong>{{ importStage }}</strong><span>{{ importProgress }}%</span></div>
        <el-progress :percentage="importProgress" :status="importProgress === 100 ? 'success' : undefined" />
      </div>
      <div v-if="importPreview" class="import-preview" data-testid="cost-import-preview">
        <strong>预检结果：{{ importPreview.valid }} / {{ importPreview.total }} 行可导入</strong>
        <span>失败 {{ importPreview.errors?.length || 0 }} 行。只有零错误才可确认入账。</span>
        <span v-if="importPreview.error_batch_id">异常批次：{{ importPreview.error_batch_id }}（已记录）</span>
        <el-button v-if="importPreview.errors?.length" plain type="danger" data-testid="cost-error-export" @click="exportImportErrors">导出完整异常明细</el-button>
        <el-table v-if="importPreview.errors?.length" :data="importPreview.errors.slice(0, 20)" size="small" border>
          <el-table-column prop="row" label="行" width="70" />
          <el-table-column prop="code" label="错误码" width="150" />
          <el-table-column prop="message" label="原因" />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button :disabled="!importFile" :loading="importing" @click="previewImport">校验预览</el-button>
        <el-button type="primary" :disabled="!importPreview || importPreview.errors?.length || !importPreview.valid" :loading="importing" @click="confirmImport">确认导入</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { confirmProductCostImport, confirmProductCostVersion, createProductCostVersion, executeProductCostBackfill, fetchCostWarehouses, fetchProductCosts, previewProductCostBackfill, previewProductCostImport } from '../../api/productCosts';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.cost.manage', 'products.cost.approve'));
const canBackfill = computed(() => auth.hasPermission('products.cost.backfill'));
const canImport = computed(() => auth.hasPermission('products.cost.backfill') && auth.hasPermission('products.cost.approve'));
const loading = ref(false);
const saving = ref(false);
const previewing = ref(false);
const rows = ref([]);
const warehouses = ref([]);
const filters = reactive({ search: '', status: '', warehouse: '' });
const applied = reactive({ search: '', status: '', warehouse: '' });
const drawerVisible = ref(false);
const drawerReadonly = ref(true);
const backfillVisible = ref(false);
const historyVisible = ref(false);
const historyRows = ref([]);
const historySku = ref('');
const historyWarehouse = ref('');
const preview = ref(null);
const importVisible = ref(false);
const importFile = ref(null);
const importPreview = ref(null);
const importing = ref(false);
const importProgress = ref(0);
const importStage = ref('');
const backfill = reactive({ scope: 'pending', rule: 'latest', warehouse: '', effective_from: new Date().toISOString().slice(0, 10) });
watch(() => [backfill.warehouse, backfill.scope, backfill.rule, backfill.effective_from], () => { preview.value = null; });
const form = reactive({});
const statusMeta = {
  pending: { label: '待核对', type: 'warning' },
  difference: { label: '存在差异', type: 'danger' },
  confirmed: { label: '已确认', type: 'success' }
};

const visibleRows = computed(() => rows.value.filter((row) => {
  const term = applied.search.trim().toLowerCase();
  const matchesSearch = !term || [row.sku_code, row.spu_code, row.product_name].some((value) => String(value || '').toLowerCase().includes(term));
  return matchesSearch && (!applied.status || row.status === applied.status) && (!applied.warehouse || row.warehouse === applied.warehouse);
}));
const calculatedFormCost = computed(() => money(['purchase_price', 'freight_cost', 'duty_cost', 'packaging_cost', 'other_cost'].reduce((sum, key) => sum + number(form[key]), 0)));
const changeAmount = computed(() => number(form.confirmed_cost) - number(form.original_confirmed_cost));
const changeRate = computed(() => number(form.original_confirmed_cost) ? `${changeAmount.value >= 0 ? '+' : ''}${(changeAmount.value / number(form.original_confirmed_cost) * 100).toFixed(2)}%` : '首个成本版本');

const number = (value) => Number(value || 0);
const money = (value) => value === null || value === undefined || value === '' ? '-' : `¥${number(value).toFixed(2)}`;
const signedMoney = (value) => `${value >= 0 ? '+' : '-'}¥${Math.abs(value).toFixed(2)}`;
const extraCost = (row) => number(row.freight_cost) + number(row.duty_cost) + number(row.packaging_cost) + number(row.other_cost);
const statusCount = (status) => visibleRows.value.filter((row) => row.status === status).length;
const difference = (row) => row.confirmed_cost === null ? '-' : `${number(row.confirmed_cost) - number(row.system_cost) >= 0 ? '+' : ''}${(number(row.confirmed_cost) - number(row.system_cost)).toFixed(2)}`;
const differenceClass = (row) => Math.abs(number(row.confirmed_cost) - number(row.system_cost)) > 0.009 ? 'difference-value' : 'muted';

async function load() {
  loading.value = true;
  const [response, warehouseResponse] = await Promise.all([fetchProductCosts(), fetchCostWarehouses()]);
  loading.value = false;
  if (!response.success) return ElMessage.error(response.message || '商品成本加载失败');
  if (!warehouseResponse.success) ElMessage.error(warehouseResponse.message || '仓库档案加载失败，无法选择仓库');
  warehouses.value = warehouseResponse.success ? (Array.isArray(warehouseResponse.data) ? warehouseResponse.data : (warehouseResponse.data?.items || [])) : [];
  const versions = Array.isArray(response.data) ? response.data : (response.data?.items || []);
  const grouped = new Map();
  versions.forEach((version) => {
    const key = `${version.sku}:${version.warehouse || 'legacy'}`;
    const item = grouped.get(key) || { id: key, sku_id: version.sku, sku_code: version.sku_code, product_name: version.product_name, warehouse: version.warehouse, warehouse_code: version.warehouse_code, warehouse_name: version.warehouse_name, warehouse_country_code: version.warehouse_country_code, versions: [] };
    item.versions.push({ ...version, cost: version.confirmed_cost, source: version.source === 'manual' ? '人工维护' : '系统生成' });
    grouped.set(key, item);
  });
  rows.value = [...grouped.values()].map((item) => {
    item.versions.sort((a, b) => Number(b.version_no) - Number(a.version_no));
    const current = item.versions.find((version) => !version.effective_to) || item.versions[0];
    return { ...item, ...current, id: item.id, version_id: current.id, purchase_price: current.purchase_cost, version_no: `V${current.version_no}`, effective_date: String(current.effective_from || '').slice(0, 10), versions: item.versions.map((version) => ({ ...version, version_no: `V${version.version_no}`, effective_from: String(version.effective_from || '').slice(0, 10), effective_to: version.effective_to ? String(version.effective_to).slice(0, 10) : null })) };
  });
}
function applyFilters() { Object.assign(applied, filters); }
function resetFilters() { Object.assign(filters, { search: '', status: '', warehouse: '' }); applyFilters(); }
function openDrawer(row, readonly) { Object.assign(form, row, { reason: '', original_confirmed_cost: row.confirmed_cost }); drawerReadonly.value = readonly; drawerVisible.value = true; }
function inspect(row) { openDrawer(row, true); }
function edit(row) { openDrawer(row, false); }
function showHistory(row) { historySku.value = row.sku_code; historyWarehouse.value = `${row.warehouse_name || row.warehouse_code || '未归属仓库（历史）'}（${row.warehouse_country_code || '-'}）`; historyRows.value = row.versions || []; historyVisible.value = true; }
function adoptSystemCost() { form.confirmed_cost = number(calculatedFormCost.value.replace('¥', '')).toFixed(4); }
async function save() {
  if (!String(form.reason || '').trim()) return ElMessage.warning('请填写调整原因');
  if (form.status !== 'pending' && !form.effective_from) return ElMessage.warning('请选择新版本生效日期');
  if (form.confirmed_cost === '' || Number.isNaN(Number(form.confirmed_cost))) return ElMessage.warning('请填写有效的商品成本');
  if (!form.warehouse) return ElMessage.warning('请先通过带仓库编码的模板建立仓库成本');
  saving.value = true;
  const payload = { sku: form.sku_id, warehouse: form.warehouse, purchase_cost: form.purchase_price, freight_cost: form.freight_cost, duty_cost: form.duty_cost, packaging_cost: form.packaging_cost, other_cost: form.other_cost, system_cost: calculatedFormCost.value.replace('¥', ''), confirmed_cost: form.confirmed_cost, reason: form.reason, status: 'confirmed', source: 'manual' };
  payload.effective_from = new Date(`${form.effective_from}T00:00:00`).toISOString();
  const response = form.status === 'pending'
    ? await confirmProductCostVersion(form.version_id, { confirmed_cost: form.confirmed_cost, reason: form.reason })
    : await createProductCostVersion(payload);
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '商品成本保存失败');
  drawerVisible.value = false;
  ElMessage.success('新成本版本已确认，历史版本已保留');
  await load();
}
function openBackfill() { preview.value = null; backfillVisible.value = true; }
function openImport() { resetImport(); importVisible.value = true; }
function downloadImportTemplate() {
  const headers = ['SKU编码（二选一）', '旧SKU编码（二选一）', '*仓库编码', '*生效开始', '生效结束', '*币种', '采购成本', '物流分摊', '税费', '包装费', '其他费用', '*确认成本', '调整原因'];
  const blob = new Blob([`\uFEFF${headers.join(',')}\r\n`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '商品成本导入模板.csv';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
function selectImportFile(uploadFile) { importFile.value = uploadFile.raw; importPreview.value = null; importProgress.value = 0; importStage.value = ''; }
function resetImportFile() { importFile.value = null; importPreview.value = null; importProgress.value = 0; importStage.value = ''; }
function resetImport() { resetImportFile(); importing.value = false; }
function updateImportUploadProgress(event, uploadStage, processingStage) {
  if (!event.total) return;
  const ratio = Math.min(event.loaded / event.total, 1);
  if (ratio >= 1) {
    importStage.value = processingStage;
    importProgress.value = 60;
    return;
  }
  importStage.value = uploadStage;
  importProgress.value = Math.max(5, Math.round(ratio * 45));
}
function exportImportErrors() {
  const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const rows = [['异常批次', '行号', '字段', '错误原因'], ...(importPreview.value?.errors || []).map((item) => [importPreview.value.error_batch_id || '', item.row || '', item.field || item.code || '', item.message || ''])];
  const blob = new Blob([`\uFEFF${rows.map((row) => row.map(quote).join(',')).join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `商品成本导入异常_${importPreview.value?.error_batch_id || 'preview'}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
async function previewImport() {
  if (!importFile.value) return;
  importing.value = true;
  importProgress.value = 5;
  importStage.value = '正在上传文件';
  const response = await previewProductCostImport(importFile.value, (event) => updateImportUploadProgress(event, '正在上传文件', '正在解析并校验数据'));
  importing.value = false;
  if (!response.success) { importStage.value = '预检失败'; return ElMessage.error(response.message || '成本导入预检失败'); }
  importPreview.value = response.data;
  importProgress.value = 100;
  importStage.value = response.data?.errors?.length ? '预检完成，请处理异常' : '预检完成，可确认导入';
}
async function confirmImport() {
  if (!importFile.value || !importPreview.value || importPreview.value.errors?.length) return;
  importing.value = true;
  importProgress.value = 5;
  importStage.value = '正在上传确认批次';
  const key = globalThis.crypto?.randomUUID?.() || `cost-import-${Date.now()}`;
  const response = await confirmProductCostImport(importFile.value, importPreview.value.token, key, (event) => updateImportUploadProgress(event, '正在上传确认批次', '正在写入成本版本'));
  importing.value = false;
  if (!response.success) { importStage.value = '导入失败'; return ElMessage.error(response.message || '成本导入失败'); }
  importProgress.value = 100;
  importStage.value = '导入完成';
  ElMessage.success(`已导入 ${response.data?.created || 0} 个成本版本`);
  importVisible.value = false;
  await load();
}
async function previewBackfill() {
  if (!backfill.warehouse) return ElMessage.warning('请选择仓库所在地');
  previewing.value = true;
  const response = await previewProductCostBackfill({ sku_ids: [], warehouse_id: backfill.warehouse, dry_run: true });
  previewing.value = false;
  if (!response.success) return ElMessage.error(response.message || '回填预览生成失败');
  const results = response.data?.results || [];
  preview.value = { matched: results.length, changed: results.filter((item) => item.action !== 'unchanged').length, unchanged: results.filter((item) => item.action === 'unchanged').length };
}
async function executeBackfill() {
  if (!backfill.warehouse) return ElMessage.warning('请选择仓库所在地');
  if (!backfill.effective_from) return ElMessage.warning('请选择生效日期');
  previewing.value = true;
  const response = await executeProductCostBackfill({ sku_ids: [], warehouse_id: backfill.warehouse, effective_from: new Date(`${backfill.effective_from}T00:00:00`).toISOString(), reason: `系统回填：${backfill.rule}` });
  previewing.value = false;
  if (!response.success) return ElMessage.error(response.message || '回填执行失败');
  ElMessage.success(`已生成 ${response.data?.created || 0} 个待核对成本版本`);
  backfillVisible.value = false;
  await load();
}

onMounted(load);
</script>

<style scoped>
.cost-page{min-width:980px;color:#172033}.page-header{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:16px}.page-header h1{margin:0;font-size:26px}.page-header p{max-width:760px;margin:7px 0 0;color:#64748b;line-height:1.6}.header-actions{display:flex;gap:10px}.definition-alert{margin-bottom:16px}.summary-strip{display:grid;grid-template-columns:repeat(4,1fr);margin-bottom:16px;border:1px solid #dbe3ee;border-radius:8px;background:#fff}.summary-strip div{padding:17px 20px;border-right:1px solid #e6ebf2}.summary-strip div:last-child{border-right:0}.summary-strip span,.summary-strip small{display:block;color:#718096;font-size:12px}.summary-strip strong{display:block;margin:7px 0 4px;font-size:25px}.summary-strip .warning{color:#d97706}.summary-strip .danger,.difference-value{color:#dc2626}.summary-strip .success{color:#16845b}.content-panel{border:1px solid #dbe3ee;border-radius:8px;background:#fff;overflow:hidden}.filters{display:flex;align-items:flex-end;gap:4px;padding:16px 16px 0}.filters :deep(.el-input){width:250px}.filters :deep(.el-select){width:160px}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#1d4ed8}.system-cost{color:#2563eb;font-weight:600}.muted{color:#94a3b8}.sku-heading{display:flex;flex-direction:column;gap:6px;padding:14px 16px;margin-bottom:18px;border-radius:7px;background:#f5f8fc}.sku-heading strong{font-size:15px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.audit-note{padding-top:14px;border-top:1px solid #e6ebf2;color:#718096;font-size:12px}.backfill-flow{display:flex;align-items:center;justify-content:center;gap:16px;margin:4px 0 22px}.backfill-flow div{display:flex;align-items:center;gap:8px;color:#334155}.backfill-flow b{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#2563eb;color:#fff}.backfill-flow i{color:#94a3b8;font-style:normal}.backfill-form{margin-top:20px}.backfill-form :deep(.el-select){width:100%}.preview-result{display:flex;flex-direction:column;gap:6px;padding:14px 16px;border:1px solid #bbf7d0;border-radius:7px;background:#f0fdf4;color:#166534}@media(max-width:1100px){.summary-strip{grid-template-columns:repeat(2,1fr)}.summary-strip div:nth-child(2){border-right:0}.summary-strip div:nth-child(-n+2){border-bottom:1px solid #e6ebf2}}@media(max-width:720px){.cost-page{min-width:0}.page-header{flex-direction:column}.summary-strip{grid-template-columns:1fr 1fr}.header-actions{width:100%}.backfill-flow{align-items:flex-start;gap:7px}.backfill-flow div{flex-direction:column;text-align:center;font-size:12px}.form-grid{grid-template-columns:1fr}}
.change-preview{display:grid;grid-template-columns:1fr auto 1fr 1fr;align-items:center;gap:12px;padding:14px;margin-bottom:18px;border:1px solid #dbeafe;border-radius:8px;background:#f8fbff}.change-preview div{display:flex;flex-direction:column;gap:4px}.change-preview span,.change-preview small{color:#64748b;font-size:12px}.change-preview strong{font-size:17px}.change-preview .change-arrow{color:#94a3b8;font-size:20px}.change-preview .change-result{padding-left:12px;border-left:1px solid #dbe3ee}
.template-guide{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:16px 0 12px;padding:16px;border:1px solid #bfdbfe;border-radius:8px;background:#eff6ff}.template-guide div,.import-tips{display:flex;flex-direction:column;gap:5px}.template-guide span,.import-tips span{color:#64748b;font-size:13px}.import-tips{margin-bottom:12px}.import-preview{display:flex;flex-direction:column;gap:10px;margin-top:16px;padding:14px;border:1px solid #dbeafe;border-radius:8px;background:#f8fbff}.template-guide+ .import-tips+ :deep(.el-upload) small{display:block;margin-top:8px;color:#94a3b8}
.import-progress{margin-top:14px}.import-progress>div{display:flex;justify-content:space-between;margin-bottom:6px;color:#475569;font-size:13px}
</style>
