<template>
  <section class="warehouse-mappings" :aria-busy="loading">
    <el-alert type="info" :closable="false" show-icon
      title="仓库 SKU 来源于最新库存快照"
      description="按仓库和来源 SKU 归集。同步时唯一精确匹配新/旧 SKU 自动关联；人工确认会更新该仓库同一来源 SKU 的历史关联，并供后续同步复用，不修改库存数量、不启动同步。" />
    <el-form inline @submit.prevent="search">
      <el-form-item label="店铺/仓库">
        <el-select v-model="query.warehouse_id" placeholder="全部仓库" clearable filterable>
          <el-option v-for="item in warehouses" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="SKU"><el-input v-model="query.search" placeholder="来源 SKU、内部新/旧 SKU" clearable /></el-form-item>
      <el-form-item label="关联状态">
        <el-select v-model="query.status" placeholder="全部" clearable>
          <el-option label="已关联" value="mapped" /><el-option label="未关联" value="unmapped" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table v-loading="loading" :data="rows" border stripe empty-text="当前范围暂无仓库库存 SKU">
      <el-table-column label="平台" width="110"><template #default>极风 WMS</template></el-table-column>
      <el-table-column prop="warehouse_name" label="店铺/仓库" min-width="160" show-overflow-tooltip />
      <el-table-column prop="warehouse_code" label="仓库编码" width="120" />
      <el-table-column prop="source_sku" label="来源 SKU" min-width="160" show-overflow-tooltip />
      <el-table-column prop="internal_legacy_sku_code" label="内部旧 SKU" min-width="160" show-overflow-tooltip />
      <el-table-column prop="internal_sku_code" label="内部新 SKU" min-width="180" show-overflow-tooltip />
      <el-table-column label="SKU 关联" width="110"><template #default="{ row }"><el-tag :type="row.internal_sku_id ? 'success' : 'warning'">{{ row.internal_sku_id ? '已关联' : '未关联' }}</el-tag></template></el-table-column>
      <el-table-column prop="on_hand_qty" label="在手（件）" width="110" />
      <el-table-column label="快照时间（UTC）" min-width="180"><template #default="{ row }">{{ utcTime(row.snapshot_at_utc) }}</template></el-table-column>
      <el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openMapping(row)">SKU 映射</el-button></template></el-table-column>
    </el-table>
    <el-pagination :current-page="query.page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="changePage" />
    <el-drawer v-model="mappingVisible" title="仓库 SKU 映射" size="min(520px, 96vw)" :close-on-click-modal="!saving" :show-close="!saving">
      <template v-if="selected">
        <p>{{ selected.warehouse_name }} · {{ selected.source_sku }}</p>
        <p>{{ ruleLabel }}</p>
        <el-alert v-if="mappingError" :title="mappingError" type="error" :closable="false" />
        <el-form label-position="top">
          <el-form-item label="关联内部 SKU">
            <el-select v-model="skuId" filterable remote :remote-method="searchCandidates" :loading="candidateLoading"
              :disabled="!canConfirm || saving" placeholder="搜索内部新 SKU 或旧 SKU" style="width:100%">
              <el-option v-for="sku in candidates" :key="sku.id" :value="sku.id" :label="`${sku.sku_code} · ${sku.legacy_sku_code || '无旧编码'}`" />
            </el-select>
          </el-form-item>
          <el-checkbox v-model="confirmed" :disabled="!canConfirm || saving">确认关联；如有旧映射，将替换该仓库同一来源 SKU 的关联</el-checkbox>
          <p v-if="!canConfirm">当前账号没有 SKU 映射确认权限，仅可查看。</p>
        </el-form>
      </template>
      <template #footer><el-button :disabled="saving" @click="mappingVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!canConfirm || !confirmed || !skuId || !mappingReady" @click="save">确认关联</el-button></template>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { fetchWarehouseSkus, fetchWarehouseSkuMapping, confirmWarehouseSkuMapping } from '../api/platformProductDetails';

const auth = useAuthStore();
const canConfirm = computed(() => auth.hasPermission('integrations.product_mapping.confirm'));
const query = reactive({ warehouse_id: '', search: '', status: '', page: 1, page_size: 20 });
const rows = ref([]), warehouses = ref([]), total = ref(0), loading = ref(false), error = ref('');
const selected = ref(null), mappingVisible = ref(false), mappingReady = ref(false), mappingError = ref('');
const candidates = ref([]), skuId = ref(null), expectedIds = ref([]), confirmed = ref(false), saving = ref(false), candidateLoading = ref(false), rule = ref('');
const ruleLabel = computed(() => ({ warehouse_history: '已存在仓库历史关联。', history_conflict: '历史关联冲突，请核对后确认。',
  exact_catalogue_code: '找到唯一精确匹配，可确认关联。', catalogue_conflict: '存在多个匹配，请人工确认。',
  seller_sku_conflict: '来源编码与卖家编码不一致，请人工核对。', unmatched: '未找到精确匹配，请搜索内部 SKU。' }[rule.value] || '正在读取映射信息。'));
let sequence = 0, candidateSequence = 0;

function utcTime(value) { return value ? new Date(value).toISOString().slice(0, 19).replace('T', ' ') : '—'; }

async function load() {
  const current = ++sequence;
  loading.value = true; error.value = '';
  try {
    const response = await fetchWarehouseSkus({ ...query });
    if (current !== sequence) return;
    if (!response?.success) throw new Error(response?.message || '仓库 SKU 加载失败');
    rows.value = response.data.results || []; total.value = response.data.count || 0;
    warehouses.value = response.data.warehouse_options || [];
  } catch (err) { if (current === sequence) { error.value = err.message; rows.value = []; total.value = 0; } }
  finally { if (current === sequence) loading.value = false; }
}

function search() { query.page = 1; load(); }
function reset() { Object.assign(query, { warehouse_id: '', search: '', status: '', page: 1 }); load(); }
function changePage(page) { query.page = page; load(); }

async function openMapping(row) {
  ++candidateSequence;
  selected.value = row; mappingVisible.value = true; mappingReady.value = false; confirmed.value = false;
  skuId.value = null; candidates.value = []; mappingError.value = ''; rule.value = '';
  try {
    const response = await fetchWarehouseSkuMapping(row.id);
    if (selected.value?.id !== row.id) return;
    if (!response?.success) throw new Error(response?.message || '映射读取失败');
    expectedIds.value = response.data.current_sku_ids;
    candidates.value = response.data.candidates; skuId.value = response.data.suggested_sku_id;
    rule.value = response.data.rule; mappingReady.value = true;
  } catch (err) { mappingError.value = err.message; }
}

async function searchCandidates(search) {
  const current = ++candidateSequence, id = selected.value.id;
  candidateLoading.value = true;
  try {
    const response = await fetchWarehouseSkuMapping(id, { search });
    if (current !== candidateSequence || selected.value?.id !== id) return;
    if (!response?.success) throw new Error(response?.message || 'SKU 查询失败');
    candidates.value = response.data.candidates;
  } catch (err) { if (current === candidateSequence) mappingError.value = err.message; }
  finally { if (current === candidateSequence) candidateLoading.value = false; }
}

async function save() {
  if (saving.value || !canConfirm.value || !confirmed.value || !mappingReady.value || !skuId.value) return;
  saving.value = true; mappingError.value = '';
  try {
    const response = await confirmWarehouseSkuMapping(selected.value.id, { sku_id: skuId.value, expected_sku_ids: expectedIds.value, confirmed: true });
    if (!response?.success) throw new Error(response?.message || '关联失败，请重新打开映射面板核对');
    ElMessage.success('仓库 SKU 已关联，未启动同步'); mappingVisible.value = false; search();
  } catch (err) { mappingError.value = err.message; }
  finally { saving.value = false; }
}

onMounted(load);
</script>

<style scoped>
.warehouse-mappings { display: grid; gap: 16px; margin-top: 16px; }
.el-form { margin-top: 12px; }
.el-select { width: 220px; }
.el-pagination { justify-content: flex-end; }
:deep(.el-checkbox) { height: auto; align-items: flex-start; }
:deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
</style>
