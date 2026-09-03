<template>
  <div class="drill-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">API 数据接入 · L1/L2 受控演练</p>
        <h1>平台操作演练</h1>
        <p>从接入配置、店铺授权、只读能力、同步任务到运行结果和异常处置，集中检查一次完整操作闭环。</p>
      </div>
      <el-button :loading="loading" @click="loadAll">刷新闭环状态</el-button>
    </header>

    <el-alert
      title="演练不会启用平台写能力；OAuth 地址仅展示和复制，不会自动跳转。人工重试仍只允许 Mock/沙箱模拟执行。"
      type="warning"
      :closable="false"
      show-icon
    />

    <el-card class="selector-card" shadow="never">
      <div class="selector-row">
        <span>演练配置</span>
        <el-select v-model="selectedConfigId" placeholder="选择平台配置" style="min-width: 320px" @change="loadContext">
          <el-option
            v-for="item in configs"
            :key="item.id"
            :label="`${item.platform} · ${item.account_alias} · ${item.environment}`"
            :value="item.id"
          />
        </el-select>
        <el-tag :type="closureReady ? 'success' : 'warning'">{{ closureReady ? '闭环可验收' : '存在待处理步骤' }}</el-tag>
      </div>
    </el-card>

    <el-steps :active="activeStep" finish-status="success" align-center class="drill-steps">
      <el-step v-for="step in steps" :key="step.title" :title="step.title" :description="step.description" :status="step.status" />
    </el-steps>

    <div v-if="blockers.length" class="blockers">
      <el-alert :title="`当前阻塞：${blockers.join('；')}`" type="error" :closable="false" show-icon />
    </div>

    <section class="grid">
      <el-card shadow="never">
        <template #header><div class="card-title"><span>1. 接入配置</span><el-button link type="primary" @click="goConfig">查看配置详情</el-button></div></template>
        <el-descriptions v-if="selectedConfig" :column="2" border>
          <el-descriptions-item label="平台">{{ selectedConfig.platform }}</el-descriptions-item>
          <el-descriptions-item label="环境"><el-tag>{{ selectedConfig.environment }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="配置状态">{{ selectedConfig.status }}</el-descriptions-item>
          <el-descriptions-item label="凭据状态">{{ selectedConfig.credential_status || '未配置' }}</el-descriptions-item>
          <el-descriptions-item label="站点">{{ (selectedConfig.regions || []).join(', ') || '—' }}</el-descriptions-item>
          <el-descriptions-item label="写入能力"><el-tag type="success">关闭</el-tag></el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="暂无可演练配置" />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-title">
            <span>2. 店铺授权</span>
            <el-button type="primary" plain :disabled="!canAuthorize || !selectedConfig" @click="openOAuthDialog">发起授权</el-button>
          </div>
        </template>
        <el-table :data="authorizations" size="small" empty-text="当前配置暂无店铺授权" @current-change="selectAuthorization">
          <el-table-column prop="store_name" label="店铺" min-width="150" />
          <el-table-column prop="region" label="站点" width="80" />
          <el-table-column prop="status" label="状态" width="105" />
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="selectAuthorization(row)">查看能力</el-button>
              <el-button link :disabled="!canRefresh" @click="confirmRefresh(row)">刷新令牌</el-button>
              <el-button link type="danger" :disabled="!canRevoke || row.status === 'revoked'" @click="confirmRevoke(row)">撤销授权</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-title"><span>3. 只读能力矩阵</span><el-button link type="primary" @click="goStores">到店铺档案配置</el-button></div></template>
        <el-table :data="capabilities" size="small" empty-text="请选择一个授权连接">
          <el-table-column prop="capability_code" label="能力" min-width="130" />
          <el-table-column label="读取" width="80"><template #default="{ row }"><el-tag :type="row.read_enabled ? 'success' : 'info'">{{ row.read_enabled ? '开启' : '关闭' }}</el-tag></template></el-table-column>
          <el-table-column label="写入" width="80"><template #default="{ row }"><el-tag :type="row.write_enabled ? 'danger' : 'success'">{{ row.write_enabled ? '异常开启' : '关闭' }}</el-tag></template></el-table-column>
          <el-table-column prop="sync_mode" label="同步方式" width="110" />
          <el-table-column prop="status" label="状态" width="100" />
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-title">
            <span>4. 同步任务</span>
            <div><el-button type="primary" plain :disabled="!canManage || !creatableResources.length" @click="openJobDialog">创建只读任务</el-button><el-button link type="primary" @click="goJobs">进入任务工作台</el-button></div>
          </div>
        </template>
        <el-table :data="relatedJobs" size="small" empty-text="当前配置暂无同步任务">
          <el-table-column prop="resource_type" label="资源" min-width="130" />
          <el-table-column prop="subject_name" label="对象" min-width="140" />
          <el-table-column prop="execution_mode" label="执行模式" width="120" />
          <el-table-column prop="health_state" label="健康" width="105" />
          <el-table-column prop="blocked_reason" label="阻塞原因" min-width="180" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-title"><span>5. 运行结果</span><el-button link type="primary" @click="goRuns">全部运行记录</el-button></div></template>
        <el-table :data="relatedRuns" size="small" empty-text="当前平台暂无运行结果">
          <el-table-column prop="run_id" label="运行 ID" min-width="170" />
          <el-table-column prop="resource_type" label="资源" width="130" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="masked_error_message" label="脱敏错误" min-width="180" show-overflow-tooltip />
          <el-table-column label="操作" width="75"><template #default="{ row }"><el-button link type="primary" @click="goRun(row)">详情</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-title"><span>6. 异常处置</span><el-button link type="primary" @click="goJobs">进入事件工作台</el-button></div></template>
        <el-table :data="relatedIncidents" size="small" empty-text="当前平台没有未解决事件">
          <el-table-column prop="resource_type" label="资源" width="130" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column prop="assignee_name" label="负责人" width="120" />
          <el-table-column prop="masked_message" label="脱敏信息" min-width="220" show-overflow-tooltip />
        </el-table>
      </el-card>
    </section>

    <el-dialog v-model="oauthDialogOpen" title="发起店铺授权" width="min(620px, 94vw)">
      <el-alert title="提交后只返回授权地址；系统不会自动打开外部平台。请复核平台、站点、回调地址和最小 scopes。" type="info" :closable="false" show-icon />
      <el-form label-width="110px" class="oauth-form">
        <el-form-item label="平台"><el-input :model-value="selectedConfig?.platform || ''" disabled /></el-form-item>
        <el-form-item label="店铺">
          <el-select v-model="oauthForm.store_id" placeholder="选择店铺" style="width: 100%">
            <el-option v-for="store in stores" :key="store.id" :label="`${store.name || store.code} · ${store.code || store.id}`" :value="store.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="站点">
          <el-select v-model="oauthForm.region" style="width: 100%"><el-option v-for="region in selectedConfig?.regions || []" :key="region" :label="region" :value="region" /></el-select>
        </el-form-item>
        <el-form-item label="回调地址"><el-input :model-value="configDetail?.callback_url || ''" disabled /></el-form-item>
        <el-form-item label="最小 scopes"><el-input :model-value="(configDetail?.scopes || []).join(', ')" disabled /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="oauthDialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="oauthSubmitting" :disabled="!oauthReady" @click="submitOAuth">确认生成授权地址</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="oauthResultOpen" title="授权地址已生成" width="min(720px, 94vw)">
      <el-alert title="请由已授权操作员复制后在受控浏览器中打开；地址不会被系统自动访问。" type="warning" :closable="false" show-icon />
      <el-input v-model="oauthUrl" type="textarea" :rows="4" readonly class="oauth-result" />
      <template #footer><el-button @click="oauthResultOpen = false">关闭</el-button><el-button type="primary" @click="copyOAuthUrl">复制地址</el-button></template>
    </el-dialog>

    <el-dialog v-model="jobDialogOpen" title="创建只读同步任务" width="min(560px, 94vw)">
      <el-alert title="新任务默认停用并使用 manual 调度；创建后请到同步任务工作台复核。此操作不会调用平台 API。" type="info" :closable="false" show-icon />
      <el-form label-width="110px" class="oauth-form">
        <el-form-item label="授权连接"><el-input :model-value="selectedAuthorization?.store_name || ''" disabled /></el-form-item>
        <el-form-item label="资源类型">
          <el-select v-model="jobForm.resource_type" placeholder="选择已启用的只读能力" style="width: 100%">
            <el-option v-for="item in creatableResources" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度"><el-input model-value="manual（默认停用）" disabled /></el-form-item>
      </el-form>
      <template #footer><el-button @click="jobDialogOpen = false">取消</el-button><el-button type="primary" :loading="jobCreating" :disabled="!jobForm.resource_type" @click="submitJob">确认创建</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { fetchStores } from '../../api/masterData';
import {
  fetchConnectionCapabilities,
  createSyncJob,
  fetchIntegrationConfigDetail,
  fetchIntegrationConfigs,
  fetchStoreAuthorizations,
  fetchSyncAlertIncidents,
  fetchSyncJobs,
  fetchSyncRuns,
  refreshStoreAuthorization,
  revokeStoreAuthorization,
  startStoreAuthorizationOAuth,
} from '../../api/integrations';

const router = useRouter();
const authStore = useAuthStore();
const loading = ref(false);
const configs = ref([]);
const stores = ref([]);
const jobs = ref([]);
const runs = ref([]);
const incidents = ref([]);
const authorizations = ref([]);
const capabilities = ref([]);
const selectedConfigId = ref(null);
const selectedAuthorizationId = ref(null);
const configDetail = ref(null);
const oauthDialogOpen = ref(false);
const oauthResultOpen = ref(false);
const oauthSubmitting = ref(false);
const oauthUrl = ref('');
const jobDialogOpen = ref(false);
const jobCreating = ref(false);
const oauthForm = reactive({ store_id: null, region: '' });
const jobForm = reactive({ resource_type: '' });

const rows = (response) => {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  return data?.results || data?.items || [];
};
const selectedConfig = computed(() => configs.value.find((item) => String(item.id) === String(selectedConfigId.value)) || null);
const selectedAuthorization = computed(() => authorizations.value.find((item) => String(item.id) === String(selectedAuthorizationId.value)) || null);
const relatedJobs = computed(() => jobs.value.filter((item) => String(item.platform) === String(selectedConfig.value?.platform) && (!item.account_alias || item.account_alias === selectedConfig.value?.account_alias)));
const relatedRuns = computed(() => runs.value.filter((item) => String(item.platform) === String(selectedConfig.value?.platform)).slice(0, 8));
const relatedIncidents = computed(() => incidents.value.filter((item) => String(item.platform) === String(selectedConfig.value?.platform) && item.status !== 'resolved'));
const credentialReady = computed(() => ['configured', 'referenced', 'verified'].includes(selectedConfig.value?.credential_status));
const authorizationReady = computed(() => authorizations.value.some((item) => ['active', 'authorized'].includes(item.status)));
const capabilityReady = computed(() => capabilities.value.some((item) => item.read_enabled && item.status === 'active') && !capabilities.value.some((item) => item.write_enabled));
const jobReady = computed(() => relatedJobs.value.length > 0);
const runReady = computed(() => relatedRuns.value.length > 0);
const incidentReady = computed(() => relatedIncidents.value.length === 0);
const closureReady = computed(() => credentialReady.value && authorizationReady.value && capabilityReady.value && jobReady.value && runReady.value && incidentReady.value);
const canAuthorize = computed(() => authStore.hasPermission('integrations.store.authorize'));
const canManage = computed(() => authStore.hasPermission('integrations.manage'));
const canRefresh = computed(() => authStore.hasPermission('integrations.store.authorize') && authStore.hasPermission('integrations.credential.rotate'));
const canRevoke = computed(() => authStore.hasPermission('integrations.store.revoke'));
const oauthReady = computed(() => Boolean(oauthForm.store_id && oauthForm.region && configDetail.value?.callback_url));
const capabilityResourceMap = { ORDER: { value: 'sales_order', label: '销售订单' }, RETURN_REFUND: { value: 'refund_return', label: '退货退款' }, INVENTORY: { value: 'inventory_snapshot', label: '库存快照' } };
const creatableResources = computed(() => capabilities.value
  .filter((item) => item.read_enabled && !item.write_enabled && item.status === 'active' && capabilityResourceMap[item.capability_code])
  .map((item) => capabilityResourceMap[item.capability_code])
  .filter((item) => !relatedJobs.value.some((job) => job.resource_type === item.value && String(job.selected_authorization_id || '') === String(selectedAuthorizationId.value || ''))));
const steps = computed(() => [
  { title: '配置', description: credentialReady.value ? '凭据就绪' : '凭据未就绪', status: credentialReady.value ? 'success' : 'error' },
  { title: '授权', description: authorizationReady.value ? '店铺已授权' : '缺少有效授权', status: authorizationReady.value ? 'success' : 'error' },
  { title: '能力', description: capabilityReady.value ? '只读能力已启用' : '能力待配置', status: capabilityReady.value ? 'success' : 'error' },
  { title: '任务', description: jobReady.value ? `${relatedJobs.value.length} 个任务` : '暂无任务', status: jobReady.value ? 'success' : 'error' },
  { title: '结果', description: runReady.value ? `${relatedRuns.value.length} 次运行` : '暂无运行', status: runReady.value ? 'success' : 'error' },
  { title: '处置', description: incidentReady.value ? '无未解决事件' : `${relatedIncidents.value.length} 个待处理`, status: incidentReady.value ? 'success' : 'error' },
]);
const activeStep = computed(() => {
  const firstIncomplete = steps.value.findIndex((item) => item.status !== 'success');
  return firstIncomplete === -1 ? steps.value.length : firstIncomplete;
});
const blockers = computed(() => steps.value.filter((item) => item.status !== 'success').map((item) => `${item.title}：${item.description}`));

async function loadAll() {
  loading.value = true;
  try {
    const [configResponse, jobResponse, runResponse, incidentResponse, storeResponse] = await Promise.all([
      fetchIntegrationConfigs(), fetchSyncJobs(), fetchSyncRuns(), fetchSyncAlertIncidents(), fetchStores({ page: 1, page_size: 100, status: 'active' }),
    ]);
    configs.value = rows(configResponse);
    jobs.value = rows(jobResponse);
    runs.value = rows(runResponse);
    incidents.value = rows(incidentResponse);
    stores.value = rows(storeResponse);
    if (!selectedConfigId.value && configs.value.length) selectedConfigId.value = configs.value[0].id;
    await loadContext();
  } catch (error) {
    ElMessage.error(error?.message || '演练工作台加载失败');
  } finally {
    loading.value = false;
  }
}

async function loadContext() {
  authorizations.value = [];
  capabilities.value = [];
  selectedAuthorizationId.value = null;
  configDetail.value = null;
  if (!selectedConfig.value) return;
  const [detailResponse, authorizationResponse] = await Promise.all([
    fetchIntegrationConfigDetail(selectedConfig.value.id),
    fetchStoreAuthorizations({ platform: selectedConfig.value.platform, page: 1, page_size: 100 }),
  ]);
  if (detailResponse?.success) configDetail.value = detailResponse.data;
  authorizations.value = rows(authorizationResponse).filter((item) => !item.integration_config_id || String(item.integration_config_id) === String(selectedConfig.value.id));
  const active = authorizations.value.find((item) => ['active', 'authorized'].includes(item.status)) || authorizations.value[0];
  if (active) await selectAuthorization(active);
}

async function selectAuthorization(row) {
  selectedAuthorizationId.value = row?.id || null;
  capabilities.value = [];
  if (!row?.id) return;
  const response = await fetchConnectionCapabilities(row.id);
  if (response?.success) capabilities.value = response.data?.results || [];
}

function openOAuthDialog() {
  oauthForm.store_id = selectedAuthorization.value?.store_id || stores.value[0]?.id || null;
  oauthForm.region = selectedAuthorization.value?.region || selectedConfig.value?.regions?.[0] || '';
  oauthDialogOpen.value = true;
}

async function submitOAuth() {
  if (!oauthReady.value) return;
  try {
    await ElMessageBox.confirm('确认按当前平台、站点、回调地址和最小 scopes 生成授权地址？系统不会自动打开该地址。', '确认发起授权', { type: 'warning' });
  } catch { return; }
  oauthSubmitting.value = true;
  try {
    const response = await startStoreAuthorizationOAuth({
      platform: selectedConfig.value.platform,
      integration_config_id: selectedConfig.value.id,
      store_id: oauthForm.store_id,
      region: oauthForm.region,
      redirect_uri: configDetail.value.callback_url,
      scopes: configDetail.value.scopes || [],
    });
    if (!response?.success) throw new Error(response?.message || '授权地址生成失败');
    oauthUrl.value = response.data?.auth_url || response.data?.authorization_url || '';
    if (!oauthUrl.value) throw new Error('平台未返回授权地址');
    oauthDialogOpen.value = false;
    oauthResultOpen.value = true;
  } catch (error) { ElMessage.error(error?.message || '授权地址生成失败'); }
  finally { oauthSubmitting.value = false; }
}

async function copyOAuthUrl() {
  try { await navigator.clipboard.writeText(oauthUrl.value); ElMessage.success('授权地址已复制'); }
  catch { ElMessage.warning('浏览器未允许复制，请手动选择地址'); }
}

async function confirmRefresh(row) {
  try { await ElMessageBox.confirm('确认刷新此授权的访问令牌？TikTok Shop 会同时提交 confirmed=true。', '刷新令牌', { type: 'warning' }); }
  catch { return; }
  const response = await refreshStoreAuthorization(row.id, { confirmed: true });
  if (!response?.success) return ElMessage.error(response?.message || '令牌刷新失败');
  ElMessage.success('访问令牌已刷新'); await loadContext();
}

async function confirmRevoke(row) {
  try { await ElMessageBox.confirm('撤销后相关同步任务将无法继续读取平台数据。确认撤销？', '撤销授权', { type: 'error' }); }
  catch { return; }
  const response = await revokeStoreAuthorization(row.id);
  if (!response?.success) return ElMessage.error(response?.message || '授权撤销失败');
  ElMessage.success('授权已撤销'); await loadContext();
}

function openJobDialog() {
  jobForm.resource_type = creatableResources.value[0]?.value || '';
  jobDialogOpen.value = true;
}

async function submitJob() {
  if (!selectedConfig.value || !selectedAuthorization.value || !jobForm.resource_type) return;
  try { await ElMessageBox.confirm('确认创建一个默认停用的 manual 只读同步任务？创建过程不会调用平台 API。', '确认创建同步任务', { type: 'warning' }); }
  catch { return; }
  jobCreating.value = true;
  try {
    const response = await createSyncJob({
      integration_config_id: selectedConfig.value.id,
      store_authorization_id: selectedAuthorization.value.id,
      resource_type: jobForm.resource_type,
      schedule_type: 'manual',
      is_enabled: false,
      max_retry_count: 3,
      backoff_base_seconds: 1,
    });
    if (!response?.success) throw new Error(response?.message || '同步任务创建失败');
    ElMessage.success('只读同步任务已创建，当前保持停用');
    jobDialogOpen.value = false;
    const jobResponse = await fetchSyncJobs();
    jobs.value = rows(jobResponse);
  } catch (error) { ElMessage.error(error?.message || '同步任务创建失败'); }
  finally { jobCreating.value = false; }
}

const goConfig = () => selectedConfig.value && router.push(`/integrations/configs/${selectedConfig.value.id}`);
const goStores = () => router.push('/master-data/stores');
const goJobs = () => router.push({ path: '/integrations/sync-jobs', query: { platform: selectedConfig.value?.platform || '' } });
const goRuns = () => router.push({ path: '/integrations/sync-runs', query: { platform: selectedConfig.value?.platform || '' } });
const goRun = (row) => router.push(`/integrations/sync-runs/${row.id}`);

onMounted(loadAll);
</script>

<style scoped>
.drill-page { display: grid; gap: 18px; }
.page-header, .selector-row, .card-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 2px 0 8px; color: #172033; }
.page-header p { margin: 0; color: #64748b; }
.eyebrow { color: #2563eb !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.selector-card :deep(.el-card__body) { padding: 14px 18px; }
.drill-steps { padding: 8px 0 2px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.card-title { font-weight: 700; }
.oauth-form { margin-top: 18px; }
.oauth-result { margin-top: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .page-header, .selector-row { align-items: flex-start; flex-direction: column; } }
</style>
