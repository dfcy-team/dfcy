<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="商品映射"
    subtitle="维护平台商品变体与本地 SKU 的受控映射，确认建议后才进入可用状态。"
    boundary-note="当前商品映射能力仅支持 Shopee、TikTok Shop；Lazada 已支持授权但映射尚未开放。商品映射不接收平台凭据，不自动触发商品写入、刊登或价格更新。建议确认和停用均需细粒度权限及人工确认。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button v-if="canManage" type="primary" @click="openCreate">新建商品映射</el-button>
    </template>

    <section class="toolbar" aria-label="商品映射筛选">
      <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters">
        <el-option label="Shopee" value="shopee" />
        <el-option label="TikTok Shop" value="tiktok" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="未映射" value="unmapped" />
        <el-option label="待确认建议" value="suggested" />
        <el-option label="已映射" value="mapped" />
        <el-option label="冲突" value="conflict" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <el-input v-model="filters.store_mapping_id" clearable placeholder="店铺映射 ID" @keyup.enter="applyFilters" />
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />

    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无商品映射，请先完成店铺映射或发现平台商品">
      <el-table-column prop="id" label="映射 ID" width="90" />
      <el-table-column prop="platform" label="平台" width="120" />
      <el-table-column prop="store_mapping_id" label="店铺映射" width="110" />
      <el-table-column label="平台商品 / 变体" min-width="230">
        <template #default="{ row }"><div>{{ row.platform_product_id || '-' }}</div><small>{{ row.platform_variant_id || '-' }}</small></template>
      </el-table-column>
      <el-table-column prop="platform_sku" label="平台 SKU" min-width="150" />
      <el-table-column label="本地 SKU" min-width="170">
        <template #default="{ row }"><div>{{ row.sku_code || row.sku_id || '未匹配' }}</div><small v-if="row.product_id">SPU #{{ row.product_id }}</small></template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" width="100"><template #default="{ row }">{{ row.confidence == null ? '-' : `${row.confidence}%` }}</template></el-table-column>
      <el-table-column prop="mapping_source" label="来源" width="145" />
      <el-table-column label="操作" fixed="right" width="240">
        <template #default="{ row }">
          <el-button v-if="canManage && ['suggested', 'conflict'].includes(row.status)" link type="primary" @click="openConfirm(row)">确认建议</el-button>
          <el-button v-if="canManage && row.status === 'unmapped'" link type="warning" @click="openSuggest(row)">登记建议</el-button>
          <el-button v-if="canManage && row.status !== 'inactive'" link type="danger" @click="deactivate(row)">停用</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination" aria-label="商品映射分页">
      <span class="pagination-total">共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next, jumper"
        @current-change="load"
        @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="createOpen" title="新建商品映射" width="min(620px, 94vw)" destroy-on-close>
      <el-alert title="创建先登记平台商品标识，映射初始为未映射；本页面不会自动猜测或写入本地 SKU。" type="info" show-icon :closable="false" />
      <el-form label-position="top" class="mapping-form">
        <el-form-item label="店铺映射 ID" required><el-input v-model="createForm.store_mapping_id" inputmode="numeric" /></el-form-item>
        <el-form-item label="平台商品 ID" required><el-input v-model="createForm.platform_product_id" maxlength="160" /></el-form-item>
        <el-form-item label="平台变体 ID" required><el-input v-model="createForm.platform_variant_id" maxlength="160" /></el-form-item>
        <el-form-item label="平台 SKU"><el-input v-model="createForm.platform_sku" maxlength="160" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitCreate">确认创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="confirmOpen" :title="mappingAction === 'suggest' ? '登记商品映射建议' : '确认商品映射建议'" width="min(620px, 94vw)" destroy-on-close>
      <el-alert :title="mappingAction === 'suggest' ? '登记后会将未映射记录转为待确认建议，不会直接进入已映射状态。' : '确认后会将当前建议标记为人工确认的已映射关系，请先核对平台变体和本地 SKU。'" type="warning" show-icon :closable="false" />
      <el-descriptions v-if="selectedRow" :column="1" border class="confirm-summary">
        <el-descriptions-item label="平台变体">{{ selectedRow.platform_variant_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="平台 SKU">{{ selectedRow.platform_sku || '-' }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-position="top" class="mapping-form">
        <el-form-item label="本地 SKU ID" required><el-input v-model="confirmForm.sku_id" inputmode="numeric" placeholder="填写需要绑定的租户内 SKU ID" /></el-form-item>
        <el-form-item label="置信度"><el-input-number v-model="confirmForm.confidence" :min="0" :max="100" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="confirmOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitConfirm">{{ mappingAction === 'suggest' ? '确认登记建议' : '确认映射' }}</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { confirmProductMapping, createProductMapping, deactivateProductMapping, fetchProductMappings, suggestProductMapping } from '../../api/integrations';

const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const rows = ref([]);
const filters = reactive({ platform: '', status: '', store_mapping_id: '' });
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const createOpen = ref(false);
const confirmOpen = ref(false);
const selectedRow = ref(null);
const mappingAction = ref('confirm');
const createForm = reactive({ store_mapping_id: '', platform_product_id: '', platform_variant_id: '', platform_sku: '' });
const confirmForm = reactive({ sku_id: '', confidence: 0 });
const canManage = computed(() => auth.hasPermission('integrations.store.authorize'));

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function statusLabel(value) { return ({ unmapped: '未映射', suggested: '待确认建议', mapped: '已映射', conflict: '冲突', inactive: '停用' })[value] || value || '未知'; }
function statusType(value) { return ({ unmapped: 'info', suggested: 'warning', mapped: 'success', conflict: 'danger', inactive: 'info' })[value] || 'info'; }
async function load() {
  loading.value = true;
  error.value = '';
  const response = await fetchProductMappings({ ...filters, page: page.value, page_size: pageSize.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (response?.success) {
    rows.value = responseRows(response);
    const data = response?.data;
    total.value = Number(data?.count ?? data?.total ?? rows.value.length);
  } else {
    rows.value = [];
    total.value = 0;
    error.value = response?.message || '读取商品映射失败。';
  }
  loading.value = false;
}
function handleSizeChange(size) { pageSize.value = size; page.value = 1; load(); }
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { platform: '', status: '', store_mapping_id: '' }); applyFilters(); }
function openCreate() {
  if (!canManage.value) return ElMessage.error('当前角色没有维护商品映射的权限。');
  Object.assign(createForm, { store_mapping_id: '', platform_product_id: '', platform_variant_id: '', platform_sku: '' });
  createOpen.value = true;
}
async function submitCreate() {
  if (!canManage.value) return;
  const storeMappingId = Number(createForm.store_mapping_id);
  if (!Number.isInteger(storeMappingId) || storeMappingId < 1 || !String(createForm.platform_product_id).trim() || !String(createForm.platform_variant_id).trim()) return ElMessage.warning('请填写店铺映射 ID、平台商品 ID 和变体 ID。');
  try { await ElMessageBox.confirm('确认登记该平台商品变体？映射将先保持未映射状态。', '确认创建', { type: 'warning' }); } catch { return; }
  saving.value = true;
  const response = await createProductMapping({ store_mapping_id: storeMappingId, platform_product_id: String(createForm.platform_product_id).trim(), platform_variant_id: String(createForm.platform_variant_id).trim(), platform_sku: String(createForm.platform_sku || '').trim() });
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '商品映射创建失败。');
  createOpen.value = false;
  ElMessage.success('商品映射已创建，等待建议确认。');
  await load();
}
function openConfirm(row) {
  if (!canManage.value) return ElMessage.error('当前角色没有确认商品映射的权限。');
  if (!['suggested', 'conflict'].includes(row.status)) return ElMessage.warning('未映射记录请先登记建议，不能直接确认。');
  selectedRow.value = row;
  mappingAction.value = 'confirm';
  Object.assign(confirmForm, { sku_id: row.sku_id || '', confidence: row.confidence ?? 0 });
  confirmOpen.value = true;
}
function openSuggest(row) {
  if (!canManage.value) return ElMessage.error('当前角色没有登记商品映射建议的权限。');
  if (row.status !== 'unmapped') return ElMessage.warning('只有未映射记录可以登记建议。');
  selectedRow.value = row;
  mappingAction.value = 'suggest';
  Object.assign(confirmForm, { sku_id: row.sku_id || '', confidence: row.confidence ?? 0 });
  confirmOpen.value = true;
}
async function submitConfirm() {
  if (!selectedRow.value || !canManage.value) return;
  const skuId = Number(confirmForm.sku_id);
  if (!Number.isInteger(skuId) || skuId < 1) return ElMessage.warning('请填写有效的本地 SKU ID。');
  const suggesting = mappingAction.value === 'suggest';
  if (suggesting && selectedRow.value.status !== 'unmapped') return ElMessage.warning('只有未映射记录可以登记建议。');
  if (!suggesting && !['suggested', 'conflict'].includes(selectedRow.value.status)) return ElMessage.warning('未映射记录请先登记建议，不能直接确认。');
  try {
    await ElMessageBox.confirm(
      suggesting ? '确认登记该商品映射建议？登记后仍需人工确认才会成为已映射关系。' : '确认将该建议标记为人工确认的已映射关系？',
      suggesting ? '登记建议' : '确认建议',
      { type: 'warning', confirmButtonText: suggesting ? '确认登记' : '确认映射' }
    );
  } catch { return; }
  saving.value = true;
  const payload = { sku_id: skuId, confidence: Number(confirmForm.confidence) || 0 };
  const response = suggesting
    ? await suggestProductMapping(selectedRow.value.id, payload)
    : await confirmProductMapping(selectedRow.value.id, payload);
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || (suggesting ? '商品映射建议登记失败。' : '商品映射确认失败。'));
  confirmOpen.value = false;
  ElMessage.success(suggesting ? '商品映射建议已登记，等待人工确认。' : '商品映射建议已确认。');
  await load();
}
async function deactivate(row) {
  if (!canManage.value) return ElMessage.error('当前角色没有停用商品映射的权限。');
  try { await ElMessageBox.confirm('停用后该商品映射不会参与后续同步，确认停用？', '停用商品映射', { type: 'error', confirmButtonText: '确认停用' }); } catch { return; }
  saving.value = true;
  const response = await deactivateProductMapping(row.id);
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '商品映射停用失败。');
  ElMessage.success('商品映射已停用。');
  await load();
}
onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.toolbar .el-select { width: 160px; }
.toolbar .el-input { width: 170px; }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.pagination :deep(.el-pagination) { margin-left: auto; }
.page-alert { margin-bottom: 14px; }
.mapping-form { margin-top: 18px; }
.confirm-summary { margin-top: 18px; }
small { color: #64748b; }
@media (max-width: 760px) { .pagination { align-items: flex-start; flex-direction: column; } .pagination :deep(.el-pagination) { margin-left: 0; } }
</style>
