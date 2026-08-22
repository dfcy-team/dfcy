<template>
  <AppPage
    eyebrow="SC-FLOW · LOCAL API2"
    title="集货与发运控制台"
    subtitle="站点、集货单和 typed shipment 的受控动作面板。按钮只代表当前权限，后端状态刷新成功后才更新。"
    boundary-note="仅连接本地 Mock 或受控 Django API；不发送真实通知、不连接生产对象存储。download-ticket 与生产二进制上传按后端合同保持关闭。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="activeTab === 'sites' && can('supply.consolidation_site.manage')" type="primary" @click="siteDialog = true">新增站点</el-button>
      <el-button v-if="activeTab === 'consolidations' && can('supply.consolidation.create')" type="primary" @click="consolidationDialog = true">新建集货单</el-button>
      <el-button v-if="activeTab === 'shipments' && can('supply.shipment.create')" type="primary" @click="shipmentDialog = true">新建发运单</el-button>
    </template>

    <el-tabs v-model="activeTab" @tab-change="loadActive">
      <el-tab-pane label="集货站点" name="sites">
        <section class="filter-bar">
          <el-input v-model="siteSearch" clearable placeholder="站点编码 / 名称" aria-label="站点搜索" />
          <el-button type="primary" plain @click="loadSites">查询</el-button>
        </section>
        <AppState v-if="state !== 'ready' && activeTab === 'sites'" :status="state" :detail="errorMessage" @action="loadSites" />
        <el-table v-else :data="filteredSites" border stripe row-key="id">
          <el-table-column prop="site_code" label="站点编码" min-width="150" />
          <el-table-column prop="name" label="名称" min-width="170" />
          <el-table-column prop="region_code" label="区域" width="120" />
          <el-table-column label="联系地址" min-width="260"><template #default="{ row }"><span class="wrap-text">{{ siteAddress(row) }}</span></template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '有效' : '停用' }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button v-if="can('supply.consolidation_site.manage')" size="small" @click="editSite(row)">编辑</el-button>
              <el-button v-if="row.is_active && can('supply.consolidation_site.manage')" size="small" type="warning" @click="deactivateSite(row)">停用</el-button>
              <span v-else class="muted">只读</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="集货单" name="consolidations">
        <section class="filter-bar"><el-select v-model="consolidationStatus" clearable placeholder="全部状态" aria-label="集货单状态"><el-option v-for="item in consolidationStatuses" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-button type="primary" plain @click="loadConsolidations">查询</el-button></section>
        <AppState v-if="state !== 'ready' && activeTab === 'consolidations'" :status="state" :detail="errorMessage" @action="loadConsolidations" />
        <el-table v-else :data="filteredConsolidations" border stripe row-key="id">
          <el-table-column prop="consolidation_no" label="集货单号" min-width="180" />
          <el-table-column label="站点" min-width="190"><template #default="{ row }"><span class="wrap-text">{{ row.site?.name || row.site_name_snapshot || '-' }}</span></template></el-table-column>
          <el-table-column prop="status" label="状态" width="150" />
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column label="箱数" width="80"><template #default="{ row }">{{ row.allocations?.length || 0 }}</template></el-table-column>
          <el-table-column label="受控动作" min-width="440" fixed="right"><template #default="{ row }"><div class="action-row">
            <el-button v-if="can('supply.consolidation.allocate') && row.status === 'draft'" size="small" @click="openAllocate(row, 'consolidation')">分配箱</el-button>
            <el-button v-if="can('supply.consolidation.release') && row.status === 'draft'" size="small" type="primary" @click="runConsolidationAction(row, 'release')">发布</el-button>
            <el-button v-if="can('supply.consolidation.receive') && row.allocations?.length && ['released','receiving'].includes(row.status)" size="small" @click="runConsolidationAction(row, 'receive')">收货</el-button>
            <el-button v-if="can('supply.consolidation.exception.manage') && row.allocations?.length && ['released','receiving'].includes(row.status)" size="small" type="warning" @click="runConsolidationAction(row, 'exception')">异常</el-button>
            <el-button v-if="can('supply.consolidation.receive') && row.status === 'receiving'" size="small" type="success" @click="runConsolidationAction(row, 'ready')">Ready</el-button>
            <el-button v-if="can('supply.consolidation.cancel') && !['cancelled','transferred'].includes(row.status)" size="small" type="danger" plain @click="runConsolidationAction(row, 'cancel')">取消</el-button>
            <span v-if="!hasConsolidationAction(row)" class="muted">只读</span>
          </div></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="发运单" name="shipments">
        <section class="filter-bar"><el-select v-model="shipmentStatus" clearable placeholder="全部状态" aria-label="发运单状态"><el-option v-for="item in shipmentStatuses" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-button type="primary" plain @click="loadShipments">查询</el-button></section>
        <AppState v-if="state !== 'ready' && activeTab === 'shipments'" :status="state" :detail="errorMessage" @action="loadShipments" />
        <el-table v-else :data="filteredShipments" border stripe row-key="id">
          <el-table-column prop="shipment_no" label="发运单号" min-width="180" />
          <el-table-column prop="destination_country_code" label="目的国" width="90" />
          <el-table-column prop="status" label="状态" width="150" />
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column label="受控动作" min-width="540" fixed="right"><template #default="{ row }"><div class="action-row">
            <el-button v-if="can('supply.shipment.allocate') && ['draft','loading'].includes(row.status)" size="small" @click="openAllocate(row, 'shipment')">转入集货箱</el-button>
            <el-button v-if="can('supply.shipment.customs.confirm') && row.status === 'loading'" size="small" @click="runShipmentAction(row, 'customs')">报关</el-button>
            <el-button v-if="can('supply.shipment.dispatch') && ['customs_declared','dispatched'].includes(row.status)" size="small" type="primary" @click="runShipmentAction(row, 'dispatch')">发运剩余箱</el-button>
            <el-button v-if="can('supply.shipment.port_arrival.confirm') && row.status === 'dispatched'" size="small" @click="runShipmentAction(row, 'port-arrival')">到岸</el-button>
            <el-button v-if="can('supply.shipment.warehouse_arrival.confirm') && row.status === 'port_arrived'" size="small" @click="runShipmentAction(row, 'warehouse-arrival')">到仓</el-button>
            <el-button v-if="can('supply.shipment.clearance.complete') && row.status === 'warehouse_arrived'" size="small" type="success" @click="runShipmentAction(row, 'clearance')">清关</el-button>
            <el-button v-if="can('supply.shipment.cancel') && !['cancelled','cleared'].includes(row.status)" size="small" type="danger" plain @click="runShipmentAction(row, 'cancel')">取消</el-button>
            <span v-if="!hasShipmentAction(row)" class="muted">只读</span>
          </div></template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="siteDialog" :title="siteEditingId ? '编辑集货站点' : '新增集货站点'" width="min(560px, 94vw)">
      <el-form label-position="top"><div class="form-grid"><el-form-item label="站点编码"><el-input v-model="siteForm.site_code" /></el-form-item><el-form-item label="名称"><el-input v-model="siteForm.name" /></el-form-item><el-form-item label="区域"><el-input v-model="siteForm.region_code" /></el-form-item><el-form-item label="国家"><el-input v-model="siteForm.country_code" /></el-form-item><el-form-item label="地址" class="form-span"><el-input v-model="siteForm.address_line" type="textarea" /></el-form-item></div></el-form>
      <template #footer><el-button @click="siteDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitSite">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="consolidationDialog" title="新建集货单" width="min(560px, 94vw)"><el-form label-position="top"><el-form-item label="站点"><el-select v-model="consolidationForm.site_id" placeholder="选择有效站点"><el-option v-for="item in sites.filter((site) => site.is_active)" :key="item.id" :label="`${item.site_code} · ${item.name}`" :value="item.id" /></el-select></el-form-item><el-form-item label="集货单号（可选）"><el-input v-model="consolidationForm.consolidation_no" /></el-form-item></el-form><template #footer><el-button @click="consolidationDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitConsolidation">保存</el-button></template></el-dialog>
    <el-dialog v-model="shipmentDialog" title="新建发运单" width="min(560px, 94vw)"><el-form label-position="top"><el-form-item label="发运单号"><el-input v-model="shipmentForm.shipment_no" /></el-form-item><el-form-item label="目的国家"><el-input v-model="shipmentForm.destination_country_code" maxlength="2" /></el-form-item><el-form-item label="区域"><el-input v-model="shipmentForm.region_code" /></el-form-item></el-form><template #footer><el-button @click="shipmentDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitShipment">保存</el-button></template></el-dialog>
    <el-dialog v-model="allocateDialog" :title="allocateKind === 'shipment' ? '转入集货箱' : '分配物理箱'" width="min(560px, 94vw)"><el-alert title="仅提交当前数据范围内的 ID；后端会重新校验租户、供应商和版本。" type="info" :closable="false" /><el-form label-position="top"><el-form-item v-if="allocateKind === 'shipment'" label="来源集货单 ID"><el-input-number v-model="allocationConsolidationId" :min="1" /></el-form-item><el-form-item :label="allocateKind === 'shipment' ? '集货箱分配 ID（逗号分隔）' : '装箱物理箱 ID（逗号分隔）'"><el-input v-model="allocationBoxIds" :placeholder="allocateKind === 'shipment' ? '例如 301,302' : '例如 101,102'" /></el-form-item></el-form><template #footer><el-button @click="allocateDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitAllocation">提交</el-button></template></el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { useAuthStore } from '../../stores/auth';
import {
  allocateConsolidationBoxes,
  allocateShipmentBoxes,
  consolidationAction,
  consolidationAllocationAction,
  createConsolidation,
  createConsolidationSite,
  createShipment,
  deactivateConsolidationSite,
  updateConsolidationSite,
  fetchConsolidations,
  fetchShipments,
  fetchConsolidationSites,
  shipmentAction
} from '../../api/supplyFlow';

const props = defineProps({ initialTab: { type: String, default: 'sites' } });
const auth = useAuthStore();
const activeTab = ref(['sites', 'consolidations', 'shipments'].includes(props.initialTab) ? props.initialTab : 'sites');
const capability = ref('pending');
const state = ref('loading');
const errorMessage = ref('');
const submitting = ref(false);
const sites = ref([]); const consolidations = ref([]); const shipments = ref([]);
const siteSearch = ref(''); const consolidationStatus = ref(''); const shipmentStatus = ref('');
const siteDialog = ref(false); const siteEditingId = ref(null); const consolidationDialog = ref(false); const shipmentDialog = ref(false); const allocateDialog = ref(false);
const allocateKind = ref('consolidation'); const allocateTarget = ref(null); const allocationBoxIds = ref(''); const allocationConsolidationId = ref(null);
const siteForm = reactive({ site_code: '', name: '', region_code: '', country_code: 'CN', address_line: '' });
const consolidationForm = reactive({ site_id: null, consolidation_no: '' });
const shipmentForm = reactive({ shipment_no: '', region_code: '', destination_country_code: '' });
const consolidationStatuses = [{ value: 'draft', label: '草稿' }, { value: 'released', label: '已发布' }, { value: 'receiving', label: '收货中' }, { value: 'ready_for_shipment', label: '待发运' }, { value: 'transferred', label: '已转运' }, { value: 'cancelled', label: '已取消' }];
const shipmentStatuses = [{ value: 'draft', label: '草稿' }, { value: 'loading', label: '装箱中' }, { value: 'customs_declared', label: '已报关' }, { value: 'dispatched', label: '已发运（可继续）' }, { value: 'port_arrived', label: '已到岸' }, { value: 'warehouse_arrived', label: '已到仓' }, { value: 'warehouse_cleared', label: '已清关' }, { value: 'cancelled', label: '已取消' }];

const can = (permission) => auth.hasPermission(permission);
const filteredSites = computed(() => sites.value.filter((item) => !siteSearch.value || `${item.site_code} ${item.name}`.toLowerCase().includes(siteSearch.value.toLowerCase())));
const filteredConsolidations = computed(() => consolidations.value.filter((item) => !consolidationStatus.value || item.status === consolidationStatus.value));
const filteredShipments = computed(() => shipments.value.filter((item) => !shipmentStatus.value || item.status === shipmentStatus.value));
const siteAddress = (item) => [item.country_code, item.province_state, item.city, item.address_line].filter(Boolean).join(' · ') || '-';

async function loadSites() { await load(fetchConsolidationSites, {}, (data) => { sites.value = data.results || []; }); }
async function loadConsolidations() { await load(fetchConsolidations, {}, (data) => { consolidations.value = data.results || []; }); }
async function loadShipments() { await load(fetchShipments, {}, (data) => { shipments.value = data.results || []; }); }
async function loadActive() { if (activeTab.value === 'sites') return loadSites(); if (activeTab.value === 'consolidations') return loadConsolidations(); return loadShipments(); }
async function load(loader, params, assign) {
  state.value = 'loading'; errorMessage.value = '';
  const response = await loader(params);
  if (!response.success) { state.value = 'error'; errorMessage.value = response.message; return; }
  assign(response.data || {}); capability.value = response.data?.api_status || 'connected'; state.value = 'ready';
}
async function refresh(kind = activeTab.value) { if (kind === 'sites') return loadSites(); if (kind === 'consolidations') return loadConsolidations(); return loadShipments(); }
async function invoke(action, callback, kind) {
  submitting.value = true;
  const response = await callback();
  submitting.value = false;
  if (!response.success) { ElMessage.error(response.message || '操作未完成'); return; }
  ElMessage.success(response.data?.replayed ? '重复请求已复用原结果' : '操作成功，已刷新状态');
  await refresh(kind);
}
function editSite(row) { siteEditingId.value = row.id; Object.assign(siteForm, { site_code: row.site_code || '', name: row.name || '', region_code: row.region_code || '', country_code: row.country_code || '', address_line: row.address_line || '' }); siteDialog.value = true; }
async function submitSite() { if (!siteForm.site_code.trim() || !siteForm.name.trim() || !siteForm.region_code.trim()) return ElMessage.warning('请填写站点编码、名称和区域'); const editing = siteEditingId.value; const callback = editing ? () => updateConsolidationSite(editing, { ...siteForm, expected_version: sites.value.find((item) => item.id === editing)?.version || 1 }) : () => createConsolidationSite({ ...siteForm }); await invoke(editing ? 'site-update' : 'site-create', callback, 'sites'); siteDialog.value = false; siteEditingId.value = null; }
async function deactivateSite(row) { await invoke('site-deactivate', () => deactivateConsolidationSite(row.id, { expected_version: row.version, reason: 'web-console' }), 'sites'); }
async function submitConsolidation() { if (!consolidationForm.site_id) return ElMessage.warning('请选择有效站点'); await invoke('consolidation-create', () => createConsolidation({ ...consolidationForm }), 'consolidations'); consolidationDialog.value = false; }
async function runConsolidationAction(row, action) {
  const payload = { expected_version: row.version, reason: 'web-console' };
  const allocation = row.allocations?.[0];
  const callback = ['receive', 'exception'].includes(action) && allocation
    ? () => consolidationAllocationAction(row.id, allocation.id, action, { ...payload, ...(action === 'exception' ? { exception_code: 'WEB_REVIEW' } : {}) })
    : () => consolidationAction(row.id, action, payload);
  await invoke(action, callback, 'consolidations');
}
async function submitShipment() { if (!shipmentForm.shipment_no.trim() || !shipmentForm.destination_country_code.trim()) return ElMessage.warning('请填写发运单号和目的国家'); await invoke('shipment-create', () => createShipment({ ...shipmentForm }), 'shipments'); shipmentDialog.value = false; }
async function runShipmentAction(row, action) { const payload = { expected_version: row.version, reason: 'web-console' }; if (action === 'customs') payload.customs_reference = `LOCAL-${row.id}`; if (action === 'dispatch' && row.allocations?.length) payload.allocation_ids = row.allocations.filter((item) => item.state === 'transferred').map((item) => item.id); await invoke(action, () => shipmentAction(row.id, action, payload), 'shipments'); }
function openAllocate(row, kind) { allocateTarget.value = row; allocateKind.value = kind; allocationBoxIds.value = ''; allocationConsolidationId.value = row.consolidation_id || row.source_consolidation_id || null; allocateDialog.value = true; }
async function submitAllocation() { const ids = allocationBoxIds.value.split(',').map((value) => Number(value.trim())).filter((value) => Number.isInteger(value) && value > 0); if (!ids.length || !allocateTarget.value) return ElMessage.warning('请输入至少一个有效箱 ID'); const row = allocateTarget.value; const payload = allocateKind.value === 'shipment' ? { expected_version: row.version, consolidation_id: Number(allocationConsolidationId.value), allocation_ids: ids } : { expected_version: row.version, box_ids: ids }; if (allocateKind.value === 'shipment' && !Number.isInteger(payload.consolidation_id)) return ElMessage.warning('请输入来源集货单 ID'); await invoke('allocate', () => allocateKind.value === 'shipment' ? allocateShipmentBoxes(row.id, payload) : allocateConsolidationBoxes(row.id, payload), allocateKind.value === 'shipment' ? 'shipments' : 'consolidations'); allocateDialog.value = false; }
function hasConsolidationAction(row) { return (row.status === 'draft' && (can('supply.consolidation.allocate') || can('supply.consolidation.release'))) || (row.allocations?.length && ['released','receiving'].includes(row.status) && (can('supply.consolidation.receive') || can('supply.consolidation.exception.manage'))) || (row.status === 'receiving' && can('supply.consolidation.receive')) || (can('supply.consolidation.cancel') && !['cancelled','transferred'].includes(row.status)); }
function hasShipmentAction(row) { return (['draft','loading'].includes(row.status) && can('supply.shipment.allocate')) || (row.status === 'loading' && can('supply.shipment.customs.confirm')) || (['customs_declared','dispatched'].includes(row.status) && can('supply.shipment.dispatch')) || (row.status === 'dispatched' && can('supply.shipment.port_arrival.confirm')) || (row.status === 'port_arrived' && can('supply.shipment.warehouse_arrival.confirm')) || (row.status === 'warehouse_arrived' && can('supply.shipment.clearance.complete')) || (can('supply.shipment.cancel') && !['cancelled','warehouse_cleared'].includes(row.status)); }
onMounted(loadActive);
</script>

<style scoped>
.filter-bar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.filter-bar .el-input { max-width: 280px; }
.filter-bar .el-select { width: 180px; }
.action-row { display: flex; flex-wrap: wrap; gap: 6px; }
.wrap-text { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
.muted { color: #94a3b8; font-size: 12px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.form-span { grid-column: 1 / -1; }
:deep(.el-table) { width: 100%; }
:deep(.el-tabs__content) { overflow: visible; }
@media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } .form-span { grid-column: auto; } :deep(.el-table) { min-width: 760px; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition: none !important; } }
</style>
