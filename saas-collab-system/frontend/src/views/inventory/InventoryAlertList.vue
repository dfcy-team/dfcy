<template>
  <AppPage title="库存预警" eyebrow="库存决策" subtitle="查看真实库存风险，并记录负责人、处理方案和截止日期。" boundary-note="跟进记录不会自动下单或通知供应商。" :capability="loadError ? 'degraded' : 'connected'">
    <el-tabs v-model="activeTab" @tab-change="tabChanged">
      <el-tab-pane label="有效预警" name="alerts">
    <div class="toolbar">
      <el-select v-model="validity" aria-label="预警范围" @change="loadAlerts"><el-option label="有效预警" value="valid"/><el-option label="查看历史（含已关闭）" value="all"/></el-select>
      <el-input v-model="filters.search" clearable placeholder="搜索 SKU / 商品" aria-label="关键词" @keyup.enter="loadAlerts" />
      <el-input v-model="filters.country_code" clearable placeholder="国家代码" aria-label="国家代码" @keyup.enter="loadAlerts" />
      <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="状态筛选" @change="loadAlerts"><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select>
      <el-select v-model="filters.alert_type" clearable placeholder="全部类型" aria-label="类型筛选" @change="loadAlerts"><el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select>
      <el-select v-model="filters.severity" clearable placeholder="全部等级" aria-label="等级筛选" @change="loadAlerts"><el-option v-for="item in severityOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select>
      <el-button :loading="loading" @click="loadAlerts">刷新</el-button>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" />
    <el-alert v-if="!canManage" type="info" :closable="false" title="当前为只读视图。负责人和处理信息由有库存预警维护权限的运营或采购人员更新。" />
    <el-table :data="rows" v-loading="loading" border row-key="id" class="alerts-table">
      <el-table-column prop="id" label="编号" width="86" />
      <el-table-column label="商品" min-width="190"><template #default="{row}"><strong>{{ row.sku_code || row.legacy_sku_code || `SPU ${row.spu || '—'}` }}</strong><div class="muted">{{ row.product_name || '商品名称未维护' }}</div></template></el-table-column>
      <el-table-column prop="warehouse_code" label="国家 / 仓库" min-width="130"><template #default="{row}">{{ locationLabel(row) }}</template></el-table-column>
      <el-table-column label="预警" min-width="140"><template #default="{row}">{{ typeLabel(row.alert_type) }}<div><el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag></div></template></el-table-column>
      <el-table-column label="覆盖天数" width="105"><template #default="{row}">{{ valueOrUnmaintained(row.coverage_days) }}</template></el-table-column>
      <el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="评估依据状态" min-width="190"><template #default="{row}"><div>{{ evaluationStatusLabel(row.evaluation_status || row.source_summary?.evaluation_status) }}</div><small>计算：{{ formatTime(row.source_summary?.evaluated_at) }}；数据：{{ formatTime(row.source_summary?.data_at) }}</small><div v-if="row.source_summary?.blocked_issues?.length" class="muted">{{ row.source_summary.blocked_issues.map(issueLabel).join('、') }}</div></template></el-table-column>
      <el-table-column label="负责人" min-width="125"><template #default="{row}">{{ row.assigned_to_name || '未分配' }}</template></el-table-column>
      <el-table-column label="截止日期" width="120"><template #default="{row}">{{ row.due_date || '未维护' }}</template></el-table-column>
      <el-table-column label="操作" width="190" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openDetail(row)">详情</el-button><el-button v-if="canManage && row.status !== 'closed'" link type="primary" :disabled="auth.authorizationStale" @click="openEditor(row)">跟进</el-button><el-button v-if="['stockout_risk', 'low_coverage'].includes(row.alert_type) && auth.hasPermission('replenishment.view')" link type="primary" @click="openReplenishment(row)">补货建议</el-button></template></el-table-column>
      <template #empty><el-empty :description="loading ? '正在读取库存预警' : '暂无库存预警'" /></template>
    </el-table>
    <div class="pagination"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @change="loadAlerts" /></div>
      </el-tab-pane>
      <el-tab-pane label="评估状态" name="assessment"><CountryInventoryDecisions v-if="activeTab === 'assessment'" mode="assessment" impact="alerts" /></el-tab-pane>
      <el-tab-pane label="待核对数据" name="pending"><CountryInventoryDecisions v-if="activeTab === 'pending'" mode="pending" impact="alerts" /></el-tab-pane>
    </el-tabs>

    <el-drawer v-model="detailOpen" title="库存预警详情" size="min(640px, 96vw)">
      <template v-if="selected">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="商品">{{ selected.sku_code || selected.legacy_sku_code || `SPU ${selected.spu || '—'}` }} · {{ selected.product_name || '商品名称未维护' }}</el-descriptions-item>
          <el-descriptions-item label="类型 / 等级">{{ typeLabel(selected.alert_type) }} / {{ severityLabel(selected.severity) }}</el-descriptions-item>
          <el-descriptions-item label="预警原因">{{ selected.reason || '未维护' }}</el-descriptions-item>
          <el-descriptions-item label="评估依据状态 / 时间">{{ evaluationStatusLabel(selected.evaluation_status || selected.source_summary?.evaluation_status) }}；计算 {{ formatTime(selected.source_summary?.evaluated_at) }}；数据 {{ formatTime(selected.source_summary?.data_at) }}</el-descriptions-item>
          <el-descriptions-item label="待核对原因">{{ selected.source_summary?.blocked_issues?.map(issueLabel).join('、') || '暂无' }}</el-descriptions-item>
          <el-descriptions-item :label="selected.source_summary?.mode === 'real_observation' ? '可用库存 / 按期到货' : '可用库存 / 在途'">{{ valueOrUnmaintained(selected.available_stock) }} / {{ valueOrUnmaintained(selected.in_transit_stock) }}</el-descriptions-item>
          <el-descriptions-item label="日均销量 / 覆盖天数">{{ valueOrUnmaintained(selected.average_daily_sales) }} / {{ valueOrUnmaintained(selected.coverage_days) }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ selected.assigned_to_name || '未分配' }}</el-descriptions-item>
          <el-descriptions-item label="处理方案">{{ selected.action_plan || '未维护' }}</el-descriptions-item>
          <el-descriptions-item label="截止日期">{{ selected.due_date || '未维护' }}</el-descriptions-item>
          <el-descriptions-item label="处理结果">{{ selected.resolution || '未维护' }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ selected.version }}</el-descriptions-item>
        </el-descriptions>
        <h3>处理记录</h3><el-timeline><el-timeline-item v-for="event in selected.events || []" :key="event.id" :timestamp="formatTime(event.created_at)" placement="top"><strong>{{ eventLabel(event.event_type) }}</strong><pre>{{ JSON.stringify(event.detail, null, 2) }}</pre></el-timeline-item></el-timeline>
      </template>
    </el-drawer>

    <el-dialog v-model="editorOpen" title="更新预警跟进" width="min(560px, 96vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
      <el-alert v-if="saveError" type="error" :closable="false" :title="saveError" />
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="负责人"><el-select v-model="form.assigned_to_id" clearable placeholder="未分配" :disabled="saving || !canManage"><el-option v-for="person in assignees" :key="person.id" :label="person.name" :value="person.id" /></el-select></el-form-item>
        <el-form-item label="处理方案"><el-input v-model="form.action_plan" type="textarea" :rows="4" maxlength="10000" show-word-limit :disabled="saving || !canManage" /></el-form-item>
        <el-form-item label="截止日期"><el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" clearable :disabled="saving || !canManage" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status" :disabled="saving || !canManage"><el-option v-for="item in editableStatusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="editorOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!canManage || auth.authorizationStale" @click="saveFollowUp">保存跟进</el-button><el-button v-if="canManage" type="danger" plain :loading="saving" :disabled="auth.authorizationStale" @click="closeAlert">填写结果并关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="closeOpen" title="填写处理结果" width="min(520px, 96vw)">
      <el-alert v-if="saveError" type="error" :closable="false" :title="saveError" />
      <el-input v-model="resolutionInput" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="记录处理结果" :disabled="saving" />
      <template #footer><el-button :disabled="saving" @click="closeOpen = false">返回修改</el-button><el-button type="danger" :loading="saving" :disabled="!resolutionInput.trim() || !canManage || auth.authorizationStale" @click="submitClose">确认关闭</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import CountryInventoryDecisions from '../../components/inventory/CountryInventoryDecisions.vue';
import { useAuthStore } from '../../stores/auth';
import { closeInventoryAlert, fetchInventoryAlert, fetchInventoryAlertAssignees, fetchInventoryAlerts, updateInventoryAlertFollowUp } from '../../api/alerts';
import { useRouter } from 'vue-router';

const auth = useAuthStore();
const router = useRouter();
const canManage = computed(() => !auth.authorizationStale && auth.isInternal && auth.hasPermission('alerts.manage'));
const rows = ref([]), assignees = ref([]), total = ref(0), loading = ref(false), loadError = ref('');
const page = ref(1), pageSize = ref(20), validity = ref('valid'), activeTab = ref('alerts'), filters = reactive({ status: '', alert_type: '', severity: '', search: '', country_code: '' });
const selected = ref(null), detailOpen = ref(false), editorOpen = ref(false), closeOpen = ref(false), saving = ref(false), saveError = ref(''), resolutionInput = ref('');
const form = reactive({ assigned_to_id: null, action_plan: '', due_date: '', status: 'open' });
const statusOptions = [{ label: '待处理', value: 'open' }, { label: '已分配', value: 'assigned' }, { label: '处理中', value: 'in_progress' }, { label: '已静默', value: 'silenced' }, { label: '已关闭', value: 'closed' }];
const editableStatusOptions = statusOptions.filter(item => ['open', 'assigned', 'in_progress'].includes(item.value));
const typeOptions = [{ label: '缺货风险', value: 'stockout_risk' }, { label: '超储风险', value: 'overstock_risk' }, { label: '低覆盖', value: 'low_coverage' }, { label: '滞销', value: 'slow_moving' }];
const severityOptions = [{ label: '高', value: 'high' }, { label: '中', value: 'medium' }, { label: '低', value: 'low' }];
const statusLabel = value => statusOptions.find(item => item.value === value)?.label || '未维护';
const evaluationStatusLabel = value => ({ risk: '风险', normal: '正常', pending: '待核对', not_evaluated: '未评估', no_rules: '无规则' }[value] || '待核对');
const issueLabel = value => ({ missing_inventory_snapshot:'缺少库存快照', available_quantity_unverified:'数量来源字段待核对', inventory_source_incomplete:'库存同步未完整成功', stale_inventory_snapshot:'库存快照超过24小时', collection_coverage_unproven:'销量采集覆盖尚未证实', no_sales_facts:'无可验证销量', supply_summary_not_authorized:'缺少供应汇总权限', source_or_rules_changed:'数据或规则已更新，等待重新评估', no_active_rules:'暂无生效规则' }[value] || value);
const typeLabel = value => typeOptions.find(item => item.value === value)?.label || '未维护';
const severityLabel = value => severityOptions.find(item => item.value === value)?.label || '未维护';
const severityType = value => ({ high: 'danger', medium: 'warning', low: 'info' }[value] || 'info');
const statusType = value => ({ closed: 'success', in_progress: 'warning', assigned: 'primary', silenced: 'info' }[value] || 'info');
const valueOrUnmaintained = value => value === null || value === undefined || value === '' ? '未维护' : value;
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) : '时间未维护';
const locationLabel = row => { const code=row.warehouse_code||''; if(!code.startsWith('COUNTRY:'))return code||'未指定'; const country=code.slice(8); let name=country; try{name=new Intl.DisplayNames(['zh-CN'],{type:'region'}).of(country)||country;}catch{} return `${name}（国家汇总）`; };
const eventLabel = value => ({ triggered: '触发', deduplicated: '更新指标', assigned: '分配负责人', follow_up_updated: '更新跟进', silenced: '静默', closed: '关闭' }[value] || value);
let loadToken = 0, detailToken = 0;
watch(() => auth.authorizationStale, stale => { if (stale) assignees.value = []; });

async function loadAlerts() {
  const token = ++loadToken;
  loading.value = true; loadError.value = '';
  try {
    const params = { page: page.value, page_size: pageSize.value, validity: validity.value, source_mode: 'real_observation' };
    for (const key of Object.keys(filters)) if (filters[key]) params[key] = filters[key];
    const response = await fetchInventoryAlerts(params);
    if (token !== loadToken) return;
    if (auth.authorizationStale) throw new Error('授权信息已过期，请刷新权限后再查看。');
    if (!response?.success) throw new Error(response?.message || '库存预警读取失败。');
    const data = response.data || {};
    rows.value = Array.isArray(data.results) ? data.results : [];
    total.value = Number(data.count || 0);
    if (canManage.value) loadAssignees();
  } catch (error) { if (token === loadToken) { loadError.value = error.message || '库存预警读取失败。'; rows.value = []; total.value = 0; } }
  finally { if (token === loadToken) loading.value = false; }
}
function tabChanged(name) { activeTab.value = name; if (name === 'alerts') loadAlerts(); }
function openReplenishment(row) { router.push({ path: '/inventory/replenishment', query: { country_id: row.country_id || '', search: row.sku_code || row.legacy_sku_code || '' } }); }
async function loadAssignees() {
  const response = await fetchInventoryAlertAssignees();
  if (auth.authorizationStale || !canManage.value) { assignees.value = []; return; }
  if (response?.success) assignees.value = Array.isArray(response.data) ? response.data : [];
}
async function openDetail(row) {
  const token = ++detailToken; selected.value = { ...row }; detailOpen.value = true;
  const response = await fetchInventoryAlert(row.id);
  if (token !== detailToken || auth.authorizationStale || !response?.success) return;
  selected.value = response.data;
}
function openEditor(row) {
  if (!canManage.value || auth.authorizationStale || row.status === 'closed') return;
  selected.value = { ...row };
  Object.assign(form, { assigned_to_id: row.assigned_to_id || null, action_plan: row.action_plan || '', due_date: row.due_date || '', status: row.status === 'silenced' ? 'open' : row.status });
  saveError.value = ''; resolutionInput.value = ''; editorOpen.value = true;
}
async function saveFollowUp() {
  if (!canManage.value || auth.authorizationStale || !selected.value || saving.value) return;
  saving.value = true; saveError.value = '';
  const id = selected.value.id, expectedVersion = selected.value.version;
  const payload = { expected_version: expectedVersion, assigned_to_id: form.assigned_to_id, action_plan: form.action_plan, due_date: form.due_date || null, status: form.status };
  try {
    const response = await updateInventoryAlertFollowUp(id, payload);
    if (!response?.success) throw new Error(response?.message || '跟进保存失败。');
    if (auth.authorizationStale || selected.value?.id !== id) return;
    selected.value = response.data; rows.value = rows.value.map(row => row.id === id ? response.data : row);
    editorOpen.value = false; ElMessage.success('跟进信息已保存。');
  } catch (error) { saveError.value = error.message || '跟进保存失败。'; }
  finally { saving.value = false; }
}
function closeAlert() { if (!canManage.value || auth.authorizationStale) return; saveError.value = ''; closeOpen.value = true; }
async function submitClose() {
  if (!canManage.value || auth.authorizationStale || saving.value || !selected.value || !resolutionInput.value.trim()) return;
  saving.value = true; saveError.value = '';
  const id = selected.value.id, expectedVersion = selected.value.version;
  try {
    const response = await closeInventoryAlert(id, { reason: resolutionInput.value.trim(), expected_version: expectedVersion });
    if (!response?.success) throw new Error(response?.message || '关闭预警失败。');
    if (auth.authorizationStale || selected.value?.id !== id) return;
    selected.value = response.data; rows.value = rows.value.map(row => row.id === id ? response.data : row);
    closeOpen.value = false; editorOpen.value = false; ElMessage.success('预警已关闭，处理结果已记录。');
  } catch (error) { saveError.value = error.message || '关闭预警失败。'; }
  finally { saving.value = false; }
}
onMounted(loadAlerts);
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
.toolbar .el-select { width: 170px; }
.alerts-table { width: 100%; margin-top: 12px; }
.muted { color: #64748b; font-size: 12px; margin-top: 4px; }
.pagination { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 16px; color: #64748b; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; color: #475569; }
@media (max-width: 720px) { .toolbar, .pagination { align-items: stretch; flex-direction: column; } .toolbar .el-select { width: 100%; } }
</style>
