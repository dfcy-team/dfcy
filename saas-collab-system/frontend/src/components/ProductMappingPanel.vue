<template>
  <section v-if="standalone" class="mapping-shell" aria-label="平台商品明细 SKU 映射">
    <div class="mapping-toolbar">
      <el-select v-model="listFilters.status" clearable placeholder="全部映射状态" @change="applyListFilters">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-input v-model="listFilters.search" clearable placeholder="搜索平台商品、变体或 SKU" @keyup.enter="applyListFilters" />
      <el-button type="primary" :loading="listLoading" @click="loadStandalone">刷新</el-button>
    </div>

    <el-alert
      v-if="!canView"
      title="当前角色没有查看商品 SKU 映射的权限。"
      type="warning"
      show-icon
      :closable="false"
    />
    <el-alert
      v-else-if="!integrationEnabled"
      title="API 数据接入模块已禁用，商品映射暂不可用。请联系系统管理员启用模块后重试。"
      type="info"
      show-icon
      :closable="false"
    />
    <el-alert v-else-if="listError" :title="listError" type="error" show-icon :closable="false">
      <template #default>
        <span>{{ listError }}</span>
        <el-button link type="primary" @click="loadStandalone">重新加载</el-button>
      </template>
    </el-alert>
    <el-alert
      v-if="listFilters.status === 'unlinked' && canView && integrationEnabled"
      title="以下历史映射暂未关联到平台商品明细，仅展示原始状态和处理结果；请先完成数据核对，不要为其猜测新的平台商品。"
      type="warning"
      show-icon
      :closable="false"
    />

    <el-table
      v-if="canView && integrationEnabled"
      v-loading="listLoading"
      :data="mappingRows"
      border
      stripe
      row-key="id"
      empty-text="暂无平台商品映射，请先完成平台商品同步"
    >
      <el-table-column label="平台" width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ row.platform_name || row.platform || '-' }}</template>
      </el-table-column>
      <el-table-column label="店铺" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <div>{{ row.store_name || row.store_code || '-' }}</div>
          <small>{{ row.store_code || row.store_id || '-' }}</small>
        </template>
      </el-table-column>
      <el-table-column label="平台商品 / 变体" min-width="210" show-overflow-tooltip>
        <template #default="{ row }">
          <div>{{ row.platform_product_id || '-' }}</div>
          <small>{{ row.platform_variant_id || '-' }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="platform_sku" label="平台 SKU" min-width="140" show-overflow-tooltip />
      <el-table-column label="本地 SKU" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.mapping?.sku_code || row.internal_sku_code || row.sku_code || '未匹配' }}</template>
      </el-table-column>
      <el-table-column label="映射状态" width="130">
        <template #default="{ row }">
          <el-tag :type="statusType(rowMappingStatus(row))" effect="plain">{{ statusLabel(rowMappingStatus(row)) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="120">
        <template #default="{ row }"><el-button link type="primary" @click="openStandaloneRow(row)">查看映射</el-button></template>
      </el-table-column>
    </el-table>

    <div v-if="canView && integrationEnabled" class="mapping-pagination" aria-label="商品映射分页">
      <span>共 {{ listTotal }} 条</span>
      <el-pagination
        v-model:current-page="listPage"
        v-model:page-size="listPageSize"
        :page-sizes="[20, 50, 100]"
        :total="listTotal"
        layout="sizes, prev, pager, next, jumper"
        @current-change="loadStandalone"
        @size-change="handleListSizeChange"
      />
    </div>
  </section>

  <el-drawer
    v-model="drawerVisible"
    class="product-mapping-drawer"
    :title="drawerTitle"
    size="min(680px, 94vw)"
    destroy-on-close
    @closed="onDrawerClosed"
  >
    <div v-loading="loading" class="mapping-detail" aria-label="SKU 映射详情">
      <el-alert
        v-if="!canView"
        title="当前角色只有平台商品明细权限，不能查看 SKU 映射详情。"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-alert
        v-else-if="!integrationEnabled"
        title="API 数据接入模块已禁用，暂不能加载映射状态或执行映射操作。"
        type="info"
        show-icon
        :closable="false"
      />
      <el-alert v-else-if="unsupported" :title="unsupportedReason" type="warning" show-icon :closable="false">
        <template #default>
          <p>{{ unsupportedReason }}</p>
          <p class="mapping-help">操作指引：先在 API 数据接入中完成该平台授权和商品只读同步；平台连接器上线后，系统会在此处开放 SKU 映射。</p>
        </template>
      </el-alert>
      <el-alert v-else-if="actionError" :title="actionError" type="error" show-icon :closable="false">
        <template #default>
          <span>{{ actionError }}</span>
          <el-button link type="primary" @click="loadContext">刷新状态</el-button>
        </template>
      </el-alert>

      <template v-if="detail && !unsupported && canView && integrationEnabled">
        <section class="mapping-context">
          <div class="context-heading">
            <div>
              <strong>{{ detail.title || detail.platform_product_id || '平台商品明细' }}</strong>
              <p>{{ detail.variant || '平台变体' }}</p>
            </div>
            <el-tag :type="statusType(currentStatus)" effect="plain">{{ statusLabel(currentStatus) }}</el-tag>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="平台">{{ detail.platform_name || detail.platform || '-' }}</el-descriptions-item>
            <el-descriptions-item label="店铺">{{ detail.store_name || detail.store_code || '-' }}</el-descriptions-item>
            <el-descriptions-item label="平台商品 ID">{{ detail.platform_product_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="平台变体 ID">{{ detail.platform_variant_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="平台 SKU">{{ detail.platform_sku || '-' }}</el-descriptions-item>
            <el-descriptions-item label="当前本地 SKU">{{ mapping?.sku_code || detail.internal_sku_code || '未匹配' }}</el-descriptions-item>
          </el-descriptions>
        </section>

        <el-alert
          v-if="currentStatus === 'conflict'"
          class="mapping-conflict"
          title="当前映射存在冲突，需要重新选择本地 SKU 并人工确认。"
          type="warning"
          show-icon
          :closable="false"
        >
          <template #default><span>冲突原因：{{ mapping?.result_code || '平台变体已有其他映射关系' }}。当前 SKU：{{ currentSkuLabel }}；待确认 SKU：{{ selectedSkuLabel }}。</span></template>
        </el-alert>
        <el-alert
          v-else-if="!mapping && (detail.internal_sku_code || detail.internal_sku)"
          class="mapping-conflict"
          title="当前本地 SKU 关联尚未纳入映射确认流程。"
          type="warning"
          show-icon
          :closable="false"
        >
          <template #default><span>请先新建映射并完成建议、人工确认，系统才会将该关联计为已映射。</span></template>
        </el-alert>
        <el-alert
          v-if="detail.unlinked"
          class="mapping-conflict"
          title="该记录尚未归集到平台商品明细。"
          type="warning"
          show-icon
          :closable="false"
        >
          <template #default><span>当前仅保留历史状态和停用能力；完成平台商品明细核对后，再从明细页建立新的映射。</span></template>
        </el-alert>
        <el-alert
          v-else-if="currentStatus === 'inactive'"
          class="mapping-conflict"
          title="该映射已停用，保留历史供核对。"
          type="info"
          show-icon
          :closable="false"
        />

        <section v-if="!detail.unlinked" class="mapping-form-section">
          <div class="section-heading">
            <div>
              <strong>本地 SKU 映射</strong>
              <p>从当前租户可见的 SKU 中选择。</p>
            </div>
            <span v-if="mapping?.confidence != null" class="confidence">置信度 {{ mapping.confidence }}%</span>
          </div>
          <el-form label-position="top">
            <el-form-item label="选择本地 SKU">
              <el-select
                v-model="selectedSkuId"
                class="sku-select"
                filterable
                remote
                clearable
                :remote-method="searchSkus"
                :loading="skuLoading"
                :disabled="(!canManage && !canConfirm) || currentStatus === 'inactive'"
                placeholder="搜索 SKU 编码或商品名称"
              >
                <el-option v-for="item in skuOptions" :key="item.id" :label="skuLabel(item)" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="selectedSkuId || ['suggested', 'conflict'].includes(currentStatus)" label="置信度">
              <el-input-number v-model="confidence" :min="0" :max="100" :disabled="(!canManage && !canConfirm) || currentStatus === 'inactive'" />
            </el-form-item>
          </el-form>
          <p v-if="!skuOptions.length && canManage && currentStatus !== 'inactive'" class="mapping-help">当前没有可选的本地 SKU，请先在商品主数据中完成 SKU 建档。</p>
        </section>

        <div class="mapping-actions">
          <el-button v-if="!mapping && canManage" type="primary" :loading="saving" @click="createMapping">新建映射</el-button>
          <el-button v-if="mapping && ['unmapped', 'suggested', 'mapped'].includes(currentStatus) && canManage" type="primary" :loading="saving" @click="suggestMapping">{{ currentStatus === 'unmapped' ? '登记建议' : '调整建议' }}</el-button>
          <el-button v-if="mapping && !detail.unlinked && ['suggested', 'conflict'].includes(currentStatus) && canConfirm" type="primary" :loading="saving" @click="confirmMapping">人工确认</el-button>
          <el-button v-if="mapping && currentStatus !== 'inactive' && canManage" type="danger" plain :loading="saving" @click="deactivateMapping">停用映射</el-button>
          <el-tag v-if="!canManage && currentStatus !== 'inactive'" type="info" effect="plain">只读</el-tag>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import {
  confirmProductMapping,
  createProductMapping,
  deactivateProductMapping,
  fetchProductMappings,
  fetchProductMappingOptions,
  suggestProductMapping,
} from '../api/integrations';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  row: { type: Object, default: null },
  standalone: { type: Boolean, default: false },
  initialVariantId: { type: [String, Number], default: '' },
  initialStoreId: { type: [String, Number], default: '' },
  initialStatus: { type: String, default: '' },
});
const emit = defineEmits(['update:modelValue', 'updated']);

const auth = useAuthStore();
const drawerVisible = ref(Boolean(props.modelValue));
const detail = ref(null);
const mapping = ref(null);
const skuOptions = ref([]);
const loading = ref(false);
const skuLoading = ref(false);
const saving = ref(false);
const actionError = ref('');
const selectedSkuId = ref(null);
const confidence = ref(0);
const listLoading = ref(false);
const listError = ref('');
const mappingRows = ref([]);
const listTotal = ref(0);
const listPage = ref(1);
const listPageSize = ref(20);
const openedFromQuery = ref(false);
const listFilters = reactive({ status: props.initialStatus || '', search: '' });

const statusOptions = [
  { value: 'unmapped', label: '待映射' },
  { value: 'suggested', label: '待确认' },
  { value: 'conflict', label: '映射冲突' },
  { value: 'mapped', label: '已映射' },
  { value: 'inactive', label: '已停用' },
  { value: 'unlinked', label: '未归集历史' },
];
const canView = computed(() => auth.hasPermission('integrations.product_mapping.view'));
const canManage = computed(() => auth.hasPermission('integrations.product_mapping.manage'));
const canConfirm = computed(() => auth.hasPermission('integrations.product_mapping.confirm'));
const integrationEnabled = computed(() => auth.isModuleEnabled('api_integrations'));
const drawerTitle = computed(() => detail.value ? `SKU 映射 · ${detail.value.platform_variant_id || detail.value.platform_product_id || '平台商品'}` : 'SKU 映射');
const currentStatus = computed(() => rowMappingStatus({ ...(detail.value || {}), mapping: mapping.value }));
const currentSkuLabel = computed(() => (currentStatus.value === 'conflict' ? (detail.value?.internal_sku_code || mapping.value?.sku_code) : (mapping.value?.sku_code || detail.value?.internal_sku_code)) || '未绑定');
const selectedSkuLabel = computed(() => skuOptions.value.find((item) => String(item.id) === String(selectedSkuId.value))?.sku_code || '未选择');
const unsupported = computed(() => Boolean(detail.value) && !isSupportedPlatform(detail.value));
const unsupportedReason = computed(() => `当前平台“${detail.value?.platform_name || detail.value?.platform || '未知平台'}”暂未实现商品映射连接器。系统不会把未实现平台误显示为可操作状态。`);

function dataObject(response) {
  const data = response?.data;
  return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
}
function rowsFrom(data, key) {
  if (Array.isArray(data?.[key])) return data[key];
  if (Array.isArray(data?.results)) return data.results;
  return Array.isArray(data) ? data : [];
}
function mappingFrom(value) {
  if (!value || typeof value !== 'object') return null;
  if (value.mapping && typeof value.mapping === 'object') return value.mapping;
  if (value.mapping_summary && typeof value.mapping_summary === 'object') return value.mapping_summary;
  if (value.mapping_id) return { id: value.mapping_id, status: value.mapping_status, sku_id: value.sku_id, sku_code: value.sku_code, confidence: value.confidence, result_code: value.result_code };
  if (value.status && ['unmapped', 'suggested', 'mapped', 'conflict', 'inactive'].includes(value.status)) return value;
  return null;
}
function rowMappingStatus(row) {
  const state = mappingFrom(row?.mapping || row);
  return state?.status || 'unmapped';
}
function normalizeDetail(value) {
  if (!value || typeof value !== 'object') return null;
  return { ...value, mapping: mappingFrom(value) };
}
function normalizeSkuOptions(items) {
  return items
    .filter((item) => item && item.id != null)
    .map((item) => ({
      id: Number.isNaN(Number(item.id)) ? item.id : Number(item.id),
      sku_code: item.sku_code || item.code || '',
      legacy_sku_code: item.legacy_sku_code || '',
      product_name: item.product_name || item.name || '',
      product_id: item.product_id || item.spu_id || null,
    }));
}
function skuLabel(item) {
  const parts = [item.sku_code || `SKU ${item.id}`, item.product_name].filter(Boolean);
  return parts.join(' · ');
}
function statusLabel(value) {
  return ({ unmapped: '待映射', suggested: '待确认', mapped: '已映射', conflict: '冲突', inactive: '已停用' })[value] || '待映射';
}
function statusType(value) {
  return ({ unmapped: 'info', suggested: 'warning', mapped: 'success', conflict: 'danger', inactive: 'info' })[value] || 'info';
}
function platformCode(value) {
  return String(value?.platform_code || value?.platform || value?.platform_name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_');
}
function isSupportedPlatform(value) {
  return ['shopee', 'tiktok', 'tiktok_shop', 'tiktokshop'].includes(platformCode(value));
}
function applyMapping(value) {
  mapping.value = mappingFrom(value);
  const candidate = mapping.value?.sku_id ?? detail.value?.internal_sku_id ?? null;
  selectedSkuId.value = candidate == null ? null : (Number.isNaN(Number(candidate)) ? candidate : Number(candidate));
  confidence.value = Number(mapping.value?.confidence ?? 0);
}
function applyOptionResponse(response, preferredRow = null) {
  const data = dataObject(response);
  const details = rowsFrom(data, 'platform_details');
  if (!details.length) {
    detail.value = null;
    mapping.value = null;
    skuOptions.value = [];
    selectedSkuId.value = null;
    confidence.value = 0;
    return details;
  }
  const resolved = details.find((item) => String(item.id) === String(preferredRow?.id || props.row?.id)) || details[0];
  detail.value = normalizeDetail(resolved);
  const dataMapping = data.mapping || data.mapping_summary || mappingFrom(resolved);
  mapping.value = dataMapping || null;
  skuOptions.value = normalizeSkuOptions(rowsFrom(data, 'skus').length ? rowsFrom(data, 'skus') : data.sku_options || []);
  applyMapping({ ...(detail.value || {}), mapping: dataMapping });
  if (mapping.value?.sku_id && !skuOptions.value.some((item) => String(item.id) === String(mapping.value.sku_id))) {
    skuOptions.value.unshift({ id: mapping.value.sku_id, sku_code: mapping.value.sku_code || '', product_name: '' });
  }
  return details;
}
function findMappingForDetail(item, records) {
  return records.find((candidate) => (
    (candidate.platform_detail_id != null && String(candidate.platform_detail_id) === String(item?.id))
      || (candidate.platform_variant_id && String(candidate.platform_variant_id) === String(item?.platform_variant_id)
        && (!candidate.store_id || !item?.store_id || String(candidate.store_id) === String(item.store_id)))
  )) || null;
}
async function loadContext(context = props.row) {
  if (!canView.value || !integrationEnabled.value) return;
  if (context?.unlinked) return;
  if (!context && !props.initialVariantId) return;
  loading.value = true;
  actionError.value = '';
  const params = {
    platform_detail_id: context?.id || '',
    store_id: context?.store_id || props.initialStoreId || '',
    variant_id: context?.platform_variant_id || props.initialVariantId || '',
    page: 1,
    page_size: 100,
  };
  try {
    const response = await fetchProductMappingOptions(params);
    if (!response?.success) {
      actionError.value = response?.message || '读取商品映射状态失败，请稍后重试。';
      return;
    }
    const details = applyOptionResponse(response, context);
    if (!details.length) {
      actionError.value = '未获得该商品的映射操作上下文，请检查店铺平台关联及数据权限。';
      return;
    }
    if (!mapping.value && detail.value) {
      const mappingResponse = await fetchProductMappings({
        platform_detail_id: detail.value.id,
        store_id: detail.value.store_id || detail.value.store,
        page: 1,
        page_size: 100,
      });
      if (mappingResponse?.success) {
        const records = rowsFrom(dataObject(mappingResponse), 'results');
        const matched = findMappingForDetail(detail.value, records);
        if (matched) applyMapping({ mapping: matched });
      }
    }
  } catch (error) {
    actionError.value = error?.message || '读取商品映射状态失败，请稍后重试。';
  } finally {
    loading.value = false;
  }
}
async function loadStandalone() {
  if (!props.standalone || !canView.value || !integrationEnabled.value) return;
  listLoading.value = true;
  listError.value = '';
  try {
    if (listFilters.status === 'unlinked') {
      const response = await fetchProductMappings({
        unlinked: true,
        search: listFilters.search || undefined,
        store_id: props.initialStoreId || undefined,
        platform_variant_id: props.initialVariantId || undefined,
        page: listPage.value,
        page_size: listPageSize.value,
      });
      if (!response?.success) {
        mappingRows.value = [];
        listTotal.value = 0;
        listError.value = response?.message || '读取未归集历史失败。';
        return;
      }
      const data = dataObject(response);
      const records = rowsFrom(data, 'results').map((item) => ({ ...normalizeDetail(item), unlinked: true, mapping: item }));
      mappingRows.value = records;
      listTotal.value = Number(data.count ?? data.total ?? records.length);
      if (!openedFromQuery.value && props.initialVariantId) {
        const target = records.find((item) => String(item.platform_variant_id) === String(props.initialVariantId) && (!props.initialStoreId || String(item.store_id) === String(props.initialStoreId)));
        if (target) openStandaloneRow(target);
        openedFromQuery.value = true;
      }
      return;
    }
    const response = await fetchProductMappingOptions({
      search: listFilters.search,
      mapping_status: listFilters.status,
      store_id: props.initialStoreId || undefined,
      variant_id: props.initialVariantId || undefined,
      page: listPage.value,
      page_size: listPageSize.value,
    });
    if (!response?.success) {
      mappingRows.value = [];
      listTotal.value = 0;
      listError.value = response?.message || '读取平台商品映射失败。';
      return;
    }
    const data = dataObject(response);
    const sourceRows = rowsFrom(data, 'platform_details').map((item) => {
      const detailRow = normalizeDetail(item);
      return { ...detailRow, mapping: detailRow.mapping || null };
    });
    mappingRows.value = sourceRows;
    listTotal.value = Number(data.count ?? data.total ?? sourceRows.length);
    if (!openedFromQuery.value && props.initialVariantId) {
      const target = sourceRows.find((item) => String(item.platform_variant_id) === String(props.initialVariantId) && (!props.initialStoreId || String(item.store_id) === String(props.initialStoreId)));
      if (target) openStandaloneRow(target);
      openedFromQuery.value = true;
    }
  } catch (error) {
    mappingRows.value = [];
    listTotal.value = 0;
    listError.value = error?.message || '读取平台商品映射失败。';
  } finally {
    listLoading.value = false;
  }
}
function applyListFilters() { listPage.value = 1; loadStandalone(); }
function handleListSizeChange(size) { listPageSize.value = Number(size) || 20; listPage.value = 1; loadStandalone(); }
function openStandaloneRow(row) {
  detail.value = normalizeDetail(row);
  mapping.value = mappingFrom(row);
  drawerVisible.value = true;
  loadContext(row);
}
async function searchSkus(query) {
  if (!detail.value || (!canManage.value && !canConfirm.value)) return;
  skuLoading.value = true;
  try {
    const response = await fetchProductMappingOptions({
      platform_detail_id: detail.value.id,
      store_id: detail.value.store_id || '',
      search: String(query || '').trim(),
      page: 1,
      page_size: 100,
    });
    if (response?.success) {
      const data = dataObject(response);
      const next = normalizeSkuOptions(rowsFrom(data, 'skus').length ? rowsFrom(data, 'skus') : data.sku_options || []);
      const selected = skuOptions.value.find((item) => String(item.id) === String(selectedSkuId.value));
      skuOptions.value = selected && !next.some((item) => String(item.id) === String(selected.id)) ? [selected, ...next] : next;
    }
  } catch (error) {
    actionError.value = error?.message || '读取 SKU 候选失败，请稍后重试。';
  } finally {
    skuLoading.value = false;
  }
}
function responseMapping(response) {
  const data = dataObject(response);
  return mappingFrom(data.mapping || data.mapping_summary || data) || mappingFrom(data.platform_detail);
}
async function ensureMapping() {
  if (mapping.value?.id) return mapping.value;
  if (!detail.value?.id) {
    actionError.value = '缺少平台商品明细上下文，无法创建映射。';
    return null;
  }
  try {
    const response = await createProductMapping({ platform_detail_id: detail.value.id });
    if (!response?.success) {
      actionError.value = response?.message || '新建商品映射失败。';
      return null;
    }
    mapping.value = responseMapping(response) || { id: dataObject(response).id, status: 'unmapped' };
    applyMapping({ mapping: mapping.value });
    emit('updated', { detail: detail.value, mapping: mapping.value });
    return mapping.value;
  } catch (error) {
    actionError.value = error?.message || '新建商品映射失败，请稍后重试。';
    return null;
  }
}
async function createMapping() {
  if (!canManage.value) return ElMessage.error('当前角色没有新建商品映射的权限。');
  saving.value = true;
  await ensureMapping();
  saving.value = false;
  if (mapping.value?.id) ElMessage.success('商品映射已创建，等待登记建议。');
}
async function suggestMapping() {
  if (!canManage.value) return ElMessage.error('当前角色没有登记商品映射建议的权限。');
  if (!selectedSkuId.value) return ElMessage.warning('请先从列表中选择本地 SKU。');
  const target = await ensureMapping();
  if (!target?.id) return;
  try { await ElMessageBox.confirm('登记后将进入待确认状态，仍需具备确认权限的人员人工确认。', '登记映射建议', { type: 'warning', confirmButtonText: '确认登记' }); } catch { return; }
  saving.value = true;
  try {
    const response = await suggestProductMapping(target.id, { sku_id: selectedSkuId.value, confidence: Number(confidence.value) || 0 });
    await finishAction(response, '商品映射建议已登记，等待人工确认。');
  } catch (error) {
    actionError.value = error?.message || '商品映射建议登记失败，请稍后重试。';
  } finally {
    saving.value = false;
  }
}
async function confirmMapping() {
  if (!canConfirm.value) return ElMessage.error('当前角色没有人工确认商品映射的权限。');
  if (!selectedSkuId.value) return ElMessage.warning('请先从列表中选择本地 SKU。');
  if (!mapping.value?.id) return ElMessage.warning('请先新建或登记商品映射。');
  const expectedInternalSkuId = detail.value?.internal_sku_id || detail.value?.internal_sku || mapping.value?.existing_sku_id || null;
  const replacement = currentStatus.value === 'conflict' && expectedInternalSkuId != null;
  const confirmationText = replacement
    ? `当前 SKU 为 ${currentSkuLabel.value}，确认替换为 ${selectedSkuLabel.value} 并写入映射审计？`
    : `确认将该平台变体绑定到 ${selectedSkuLabel.value} 并写入映射审计？`;
  try { await ElMessageBox.confirm(confirmationText, '人工确认映射', { type: 'warning', confirmButtonText: '确认映射' }); } catch { return; }
  saving.value = true;
  try {
    const response = await confirmProductMapping(mapping.value.id, {
      sku_id: selectedSkuId.value,
      confidence: Number(confidence.value) || 0,
      manually_confirmed: true,
      ...(replacement ? { replace_existing: true, expected_internal_sku_id: expectedInternalSkuId } : {}),
    });
    await finishAction(response, '商品映射已人工确认。');
  } catch (error) {
    actionError.value = error?.message || '商品映射确认失败，请稍后重试。';
  } finally {
    saving.value = false;
  }
}
async function deactivateMapping() {
  if (!canManage.value) return ElMessage.error('当前角色没有停用商品映射的权限。');
  if (!mapping.value?.id) return;
  try { await ElMessageBox.confirm('停用后该映射将保留历史供核对，确认停用？', '停用商品映射', { type: 'error', confirmButtonText: '确认停用' }); } catch { return; }
  saving.value = true;
  try {
    const response = await deactivateProductMapping(mapping.value.id);
    await finishAction(response, '商品映射已停用。');
  } catch (error) {
    actionError.value = error?.message || '商品映射停用失败，请稍后重试。';
  } finally {
    saving.value = false;
  }
}
async function finishAction(response, successMessage) {
  if (!response?.success) {
    actionError.value = response?.message || '映射操作失败，请刷新状态后重试。';
    return;
  }
  actionError.value = '';
  const next = responseMapping(response);
  if (next) mapping.value = next;
  applyMapping({ mapping: mapping.value });
  emit('updated', { detail: detail.value, mapping: mapping.value });
  ElMessage.success(successMessage);
  if (props.standalone) await loadStandalone();
}
function onDrawerClosed() {
  if (!props.standalone) emit('update:modelValue', false);
}

watch(() => props.modelValue, (value) => {
  drawerVisible.value = Boolean(value);
  if (value) {
    detail.value = normalizeDetail(props.row);
    mapping.value = mappingFrom(props.row);
    loadContext(props.row);
  }
});
watch(drawerVisible, (value) => emit('update:modelValue', value));
watch(() => props.row, (value) => {
  if (!props.standalone && value) {
    detail.value = normalizeDetail(value);
    mapping.value = mappingFrom(value);
    if (drawerVisible.value) loadContext(value);
  }
}, { deep: true });
onMounted(() => {
  if (props.standalone) loadStandalone();
  else if (drawerVisible.value) {
    detail.value = normalizeDetail(props.row);
    mapping.value = mappingFrom(props.row);
    loadContext(props.row);
  }
});
</script>

<style scoped>
.mapping-shell { display: grid; gap: 14px; }
.mapping-toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.mapping-toolbar .el-select { width: 160px; }
.mapping-toolbar .el-input { width: min(300px, 100%); }
.mapping-pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 2px; color: #64748b; font-size: 13px; }
.mapping-pagination :deep(.el-pagination) { margin-left: auto; }
.mapping-detail { min-height: 260px; padding-right: 4px; }
.mapping-context { display: grid; gap: 14px; }
.context-heading, .section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.context-heading strong, .section-heading strong { color: #172033; font-size: 16px; }
.context-heading p, .section-heading p { margin: 5px 0 0; color: #64748b; font-size: 13px; line-height: 1.5; }
.mapping-conflict { margin-top: 16px; }
.mapping-form-section { margin-top: 18px; padding-top: 18px; border-top: 1px solid #e5eaf0; }
.sku-select { width: 100%; }
.mapping-help { margin: 8px 0 0; color: #8a5b00; font-size: 13px; line-height: 1.6; }
.mapping-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 22px; }
.confidence { color: #64748b; font-size: 12px; }
small { color: #64748b; }
@media (max-width: 760px) {
  .mapping-pagination { align-items: flex-start; flex-direction: column; }
  .mapping-pagination :deep(.el-pagination) { margin-left: 0; }
  .context-heading, .section-heading { flex-direction: column; }
}
</style>
