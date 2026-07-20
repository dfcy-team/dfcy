<template>
  <AppPage eyebrow="UI-P7 GOVERNANCE" :title="isAssistant ? '助手治理目录' : 'API 合同目录'" :subtitle="isAssistant ? '查看助手能力、数据级别与人工确认边界。' : '集中核对接口路径、权限、数据范围和版本。'" boundary-note="固定检查只验证合同或助手安全边界，不调用工具、不写业务数据、不连接真实平台。" :capability="capability">
    <template #action><el-button v-if="canCheck" type="primary" :loading="checking" @click="runCheck">{{ isAssistant ? '固定评估' : '合同检查' }}</el-button></template>
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="handleStateAction" />
    <template v-else>
      <div class="toolbar"><el-input v-model="keyword" clearable placeholder="名称、模块或路径" @keyup.enter="load" /><el-button @click="load">查询</el-button></div>
      <el-alert v-if="detailError" class="detail-error" type="error" :closable="false" :title="detailError" />
      <el-table :data="rows" border @row-click="openDetail">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column v-if="!isAssistant" prop="module" label="模块" width="120" />
        <el-table-column v-if="!isAssistant" prop="method" label="方法" width="90" />
        <el-table-column v-if="!isAssistant" prop="path" label="规范路径" min-width="300" show-overflow-tooltip />
        <el-table-column v-if="!isAssistant" prop="permission" label="权限" min-width="180" />
        <el-table-column v-if="isAssistant" label="数据级别" width="160"><template #default="{ row }">{{ (row.data_classes || []).join(', ') }}</template></el-table-column>
        <el-table-column v-if="isAssistant" prop="human_confirmation_required" label="人工确认" width="100"><template #default="{ row }">{{ row.human_confirmation_required ? '需要' : '不需要' }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column v-if="!isAssistant" prop="version" label="版本" width="120" />
      </el-table>
      <el-pagination class="pager" background layout="total, prev, pager, next" :total="total" :page-size="20" :current-page="page" @current-change="changePage" />
      <el-drawer v-model="drawer" title="治理详情" size="min(620px, 92vw)" @closed="closeDetailRoute">
        <el-descriptions v-if="detail" :column="1" border><el-descriptions-item v-for="(value, key) in detail" :key="key" :label="key"><pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre><span v-else>{{ value }}</span></el-descriptions-item></el-descriptions>
      </el-drawer>
      <el-alert v-if="checkResult" class="result" :type="checkFailed ? 'error' : 'success'" :closable="false" :title="JSON.stringify(checkResult)" />
    </template>
  </AppPage>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { checkApiContractMock, evaluateAssistantMock, fetchApiContract, fetchApiContracts, fetchAssistant, fetchAssistants } from '../../api/governance';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const props = defineProps({ resource: { type: String, required: true } });
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const isAssistant = computed(() => props.resource === 'assistants');
const basePath = computed(() => isAssistant.value ? '/governance/assistants' : '/governance/api-contracts');
const canCheck = computed(() => auth.hasPermission(isAssistant.value ? 'governance.assistants.evaluate' : 'governance.api.check'));
const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const detailError = ref('');
const keyword = ref('');
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const drawer = ref(false);
const detail = ref(null);
const checking = ref(false);
const checkResult = ref(null);
const checkFailed = computed(() => checkResult.value?.violations?.length > 0 || checkResult.value?.human_confirmation_required === false);

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  detailError.value = '';
  const response = isAssistant.value ? await fetchAssistants({ page: page.value, page_size: 20, search: keyword.value || undefined }) : await fetchApiContracts({ page: page.value, page_size: 20, search: keyword.value || undefined });
  if (!response.success) { state.value = statusFromApiResponse(response, navigator.onLine); errorMessage.value = response.message; return; }
  rows.value = response.data.results || [];
  total.value = response.data.count || 0;
  capability.value = response.data.api_status || 'sandbox';
  state.value = rows.value.length ? 'ready' : 'empty';
  if (route.params.id) await loadDetail(route.params.id, false);
}

async function loadDetail(id, updateRoute = true) {
  detailError.value = '';
  const response = isAssistant.value ? await fetchAssistant(id) : await fetchApiContract(id);
  if (!response.success) {
    const nextState = statusFromApiResponse(response, navigator.onLine);
    if (!updateRoute && route.params.id) {
      state.value = nextState;
      errorMessage.value = response.message;
    } else {
      detailError.value = response.message;
    }
    return;
  }
  detail.value = response.data;
  drawer.value = true;
  if (updateRoute && String(route.params.id || '') !== String(id)) await router.push(`${basePath.value}/${id}`);
}

function openDetail(row) { loadDetail(row.id); }
function closeDetailRoute() { detail.value = null; if (route.params.id) router.replace(basePath.value); }
async function handleStateAction() {
  if (state.value === 'not_found' && route.params.id) await router.replace(basePath.value);
  await load();
}
async function runCheck() {
  checking.value = true;
  const response = isAssistant.value
    ? await evaluateAssistantMock(rows.value[0]?.id || 1, { scenario: 'catalog_review', demo_input_ref: 'demo-governance-review', version: rows.value[0]?.version || 1, reason: 'fixed demo evaluation only' })
    : await checkApiContractMock({ contract_ids: rows.value.map((item) => item.id).slice(0, 50), sample_case: 'success' });
  checkResult.value = response.success ? response.data : { violations: [{ code: response.code, message: response.message }] };
  checking.value = false;
}
function changePage(value) { page.value = value; load(); }
watch(() => props.resource, () => { page.value = 1; drawer.value = false; load(); });
watch(() => route.params.id, (id) => { if (id && state.value === 'ready') loadDetail(id, false); });
load();
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; max-width: 560px; margin-bottom: 14px; }
.pager { margin-top: 16px; justify-content: flex-end; }
.result { margin-top: 16px; overflow-wrap: anywhere; }
.detail-error { margin-bottom: 14px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
</style>
