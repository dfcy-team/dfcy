<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="店铺授权"
    subtitle="查看租户内平台店铺的授权状态、范围和生命周期。"
    boundary-note="页面只展示脱敏授权元数据。发起 OAuth 只生成受控地址并要求人工确认，不会自动跳转或把平台凭据带入浏览器。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button
        v-if="canAuthorize"
        type="primary"
        @click="openOAuth"
      >发起授权</el-button>
    </template>

    <section class="toolbar" aria-label="授权筛选">
      <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters">
        <el-option label="Lazada" value="lazada" />
        <el-option label="Shopee" value="shopee" />
        <el-option label="TikTok Shop" value="tiktok" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="有效" value="active" />
        <el-option label="待授权" value="pending" />
        <el-option label="已过期" value="expired" />
        <el-option label="已撤销" value="revoked" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-input v-model="filters.store_id" clearable placeholder="店铺 ID" @keyup.enter="applyFilters" />
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="page-alert"
    />

    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无店铺授权，请先完成生产准入和 OAuth 授权">
      <el-table-column prop="id" label="授权 ID" width="90" />
      <el-table-column prop="platform" label="平台" width="120" />
      <el-table-column label="店铺" min-width="190">
        <template #default="{ row }">
          <div>{{ row.store_name || row.store_code || `店铺 #${row.store_id || '-'}` }}</div>
          <small>{{ row.store_code || `store_id=${row.store_id || '-'}` }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="region" label="区域" width="90" />
      <el-table-column prop="platform_store_id" label="平台店铺 ID" min-width="180" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="凭据" min-width="150">
        <template #default="{ row }">{{ credentialLabel(row.credential_mask) }}</template>
      </el-table-column>
      <el-table-column label="有效期" min-width="180">
        <template #default="{ row }">{{ row.expires_at || row.token_expires_at || '未提供' }}</template>
      </el-table-column>
      <el-table-column label="只读能力" min-width="120">
        <template #default="{ row }">
          {{ row.capabilities_summary?.read_enabled ?? row.capabilities_summary?.active ?? 0 }} 项
        </template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="230">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :loading="detailLoading === row.id"
            :disabled="Boolean(detailLoading && detailLoading !== row.id)"
            @click="openDetail(row)"
          >查看详情</el-button>
          <el-button
            v-if="canRefresh"
            link
            type="warning"
            :loading="actionKey === `refresh:${row.id}`"
            :disabled="Boolean(actionKey && actionKey !== `refresh:${row.id}`)"
            @click="refresh(row)"
          >刷新令牌</el-button>
          <el-button
            v-if="canRevoke && !['revoked', 'expired'].includes(row.status)"
            link
            type="danger"
            :loading="actionKey === `revoke:${row.id}`"
            :disabled="Boolean(actionKey && actionKey !== `revoke:${row.id}`)"
            @click="revoke(row)"
          >撤销授权</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination" aria-label="店铺授权分页">
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

    <el-drawer v-model="detailOpen" title="店铺授权详情" size="min(560px, 94vw)" destroy-on-close>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="授权 ID">{{ selected.id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="平台">{{ selected.platform || '-' }}</el-descriptions-item>
        <el-descriptions-item label="店铺">{{ selected.store_name || selected.store_code || selected.store_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="区域">{{ selected.region || '-' }}</el-descriptions-item>
        <el-descriptions-item label="平台店铺 ID">{{ selected.platform_store_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(selected.status) }}</el-descriptions-item>
        <el-descriptions-item label="凭据引用">{{ credentialLabel(selected.credential_mask) }}</el-descriptions-item>
        <el-descriptions-item label="授权范围">{{ (selected.scopes || []).join('、') || '未返回' }}</el-descriptions-item>
        <el-descriptions-item label="授权时间">{{ selected.authorized_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="刷新时间">{{ selected.refreshed_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="失效时间">{{ selected.expires_at || selected.token_expires_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="最后错误">{{ selected.last_error_code || '无' }}</el-descriptions-item>
      </el-descriptions>
      <p class="drawer-note">授权详情只读；能力开关请进入“能力矩阵”单独复核。</p>
      <router-link v-if="selected.id" :to="{ path: '/integrations/capabilities', query: { authorization_id: selected.id } }">打开能力矩阵</router-link>
    </el-drawer>

    <el-dialog v-model="oauthOpen" title="生成平台授权地址" width="min(620px, 94vw)" destroy-on-close>
      <el-alert
        title="仅提交平台、配置、店铺、区域、回调地址和 scopes；系统不会采集或展示 App Secret、Token 等明文凭据。"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-form label-position="top" class="oauth-form">
        <el-form-item label="平台" required>
          <el-select v-model="oauthForm.platform" style="width: 100%">
            <el-option label="Lazada" value="lazada" />
            <el-option label="Shopee" value="shopee" />
            <el-option label="TikTok Shop" value="tiktok" />
          </el-select>
        </el-form-item>
        <el-form-item label="接入配置 ID" required>
          <el-input v-model="oauthForm.integration_config_id" inputmode="numeric" placeholder="填写已通过准入检查的配置 ID" />
        </el-form-item>
        <el-form-item label="店铺 ID" required>
          <el-input v-model="oauthForm.store_id" inputmode="numeric" placeholder="填写当前租户店铺档案 ID" />
        </el-form-item>
        <el-form-item label="区域" required>
          <el-input v-model="oauthForm.region" maxlength="8" placeholder="例如 SG" />
        </el-form-item>
        <el-form-item label="HTTPS 回调地址" required>
          <el-input v-model="oauthForm.redirect_uri" type="url" placeholder="必须与接入配置一致" />
        </el-form-item>
        <el-form-item label="Scopes（逗号分隔）">
          <el-input v-model="oauthForm.scopes" placeholder="例如 order.read,shop.info" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="oauthOpen = false">取消</el-button>
        <el-button type="primary" :loading="actionKey === 'oauth'" @click="submitOAuth">确认生成地址</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="oauthResultOpen" title="授权地址已生成" width="min(700px, 94vw)" destroy-on-close>
      <el-alert title="请由具备平台操作权限的人员在受控浏览器窗口中人工打开；本系统不会自动跳转。" type="info" show-icon :closable="false" />
      <el-input :model-value="oauthUrl" readonly type="textarea" :rows="4" class="oauth-result" />
      <template #footer>
        <el-button @click="oauthResultOpen = false">关闭</el-button>
        <el-button type="primary" :loading="copying" :disabled="!oauthUrl" @click="copyOAuthUrl">复制地址</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import {
  fetchStoreAuthorizations,
  fetchStoreAuthorizationDetail,
  refreshStoreAuthorization,
  revokeStoreAuthorization,
  startStoreAuthorizationOAuth
} from '../../api/integrations';

const route = useRoute();
const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const error = ref('');
const rows = ref([]);
const actionKey = ref('');
const detailLoading = ref('');
const copying = ref(false);
const filters = reactive({ platform: normalizePlatform(route.query.platform), status: '', store_id: '' });
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const selected = ref({});
const detailOpen = ref(false);
const oauthOpen = ref(false);
const oauthResultOpen = ref(false);
const oauthUrl = ref('');
const oauthForm = reactive({ platform: normalizePlatform(route.query.platform) || 'shopee', integration_config_id: '', store_id: '', region: 'SG', redirect_uri: '', scopes: '' });

const canAuthorize = computed(() => auth.hasPermission('integrations.store.authorize'));
const canRefresh = computed(() => auth.hasPermission('integrations.store.authorize') && auth.hasPermission('integrations.credential.rotate'));
const canRevoke = computed(() => auth.hasPermission('integrations.store.revoke'));

function normalizePlatform(value) {
  const platform = String(value || '').trim().toLowerCase();
  return ['lazada', 'shopee', 'tiktok'].includes(platform) ? platform : '';
}

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function statusLabel(value) {
  return ({ active: '有效', authorized: '已授权', pending: '待授权', expired: '已过期', revoked: '已撤销', failed: '失败', error: '失败' })[value] || value || '未知';
}
function statusType(value) {
  return ({ active: 'success', authorized: 'success', pending: 'warning', expired: 'warning', revoked: 'info', failed: 'danger', error: 'danger' })[value] || 'info';
}
function credentialLabel(value) {
  if (!value) return '仅保存受控引用';
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    if (typeof value.display === 'string' && value.display.trim()) return value.display;
    if (typeof value.masked === 'string' && value.masked.trim()) return value.masked;
    if (typeof value.fingerprint === 'string' && value.fingerprint.trim()) return `受控引用 · ${value.fingerprint}`;
    if ((typeof value.version === 'string' && value.version.trim()) || (typeof value.version === 'number' && Number.isFinite(value.version))) return `受控引用 · v${value.version}`;
    return '受控引用（已脱敏）';
  }
  return '受控引用（已脱敏）';
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchStoreAuthorizations({ ...filters, page: page.value, page_size: pageSize.value });
    capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
    if (response?.success) {
      rows.value = responseRows(response);
      const data = response?.data;
      total.value = Number(data?.count ?? data?.total ?? rows.value.length);
    } else {
      rows.value = [];
      total.value = 0;
      error.value = response?.message || '读取店铺授权失败。';
    }
  } catch (requestError) {
    rows.value = [];
    total.value = 0;
    capability.value = useMock ? 'mock' : 'degraded';
    error.value = requestError?.message || '读取店铺授权失败。';
  } finally {
    loading.value = false;
  }
}
function handleSizeChange(size) { pageSize.value = size; page.value = 1; load(); }
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { platform: '', status: '', store_id: '' }); applyFilters(); }

async function openDetail(row) {
  if (detailLoading.value) return;
  detailLoading.value = row.id;
  try {
    const response = await fetchStoreAuthorizationDetail(row.id);
    if (!response?.success) return ElMessage.error(response?.message || '授权详情读取失败。');
    selected.value = response.data || row;
    detailOpen.value = true;
  } catch (requestError) {
    ElMessage.error(requestError?.message || '授权详情读取失败。');
  } finally {
    detailLoading.value = '';
  }
}

function openOAuth() {
  if (!canAuthorize.value) return ElMessage.error('当前角色没有发起店铺授权的权限。');
  Object.assign(oauthForm, { platform: filters.platform || normalizePlatform(route.query.platform) || 'shopee', integration_config_id: '', store_id: '', region: 'SG', redirect_uri: '', scopes: '' });
  oauthOpen.value = true;
}

async function submitOAuth() {
  if (!canAuthorize.value) return;
  const integrationConfigId = Number(oauthForm.integration_config_id);
  const storeId = Number(oauthForm.store_id);
  const region = String(oauthForm.region || '').trim().toUpperCase();
  const redirectUri = String(oauthForm.redirect_uri || '').trim();
  if (!Number.isInteger(integrationConfigId) || integrationConfigId < 1 || !Number.isInteger(storeId) || storeId < 1 || !region || !redirectUri.startsWith('https://')) {
    return ElMessage.warning('请填写有效的配置 ID、店铺 ID、区域和 HTTPS 回调地址。');
  }
  try {
    await ElMessageBox.confirm('确认按当前平台、店铺、回调地址和 scopes 生成授权地址？系统不会自动打开该地址。', '确认发起授权', { type: 'warning' });
  } catch { return; }
  actionKey.value = 'oauth';
  try {
    const response = await startStoreAuthorizationOAuth({
      platform: oauthForm.platform,
      integration_config_id: integrationConfigId,
      store_id: storeId,
      region,
      redirect_uri: redirectUri,
      scopes: String(oauthForm.scopes || '').split(',').map((item) => item.trim()).filter(Boolean)
    });
    if (!response?.success) return ElMessage.error(response?.message || '授权地址生成失败。');
    oauthUrl.value = response.data?.auth_url || response.data?.authorization_url || '';
    if (!oauthUrl.value) return ElMessage.error('平台未返回授权地址。');
    oauthOpen.value = false;
    oauthResultOpen.value = true;
  } catch (requestError) {
    ElMessage.error(requestError?.message || '授权地址生成失败。');
  } finally {
    actionKey.value = '';
  }
}

async function refresh(row) {
  if (!canRefresh.value) return ElMessage.error('当前角色没有刷新令牌的权限。');
  try { await ElMessageBox.confirm('确认刷新该店铺授权令牌？操作结果会记录到集成审计。', '刷新令牌', { type: 'warning' }); } catch { return; }
  actionKey.value = `refresh:${row.id}`;
  try {
    const response = await refreshStoreAuthorization(row.id, { confirmed: true });
    if (!response?.success) return ElMessage.error(response?.message || '令牌刷新失败。');
    ElMessage.success('令牌已刷新。');
    await load();
  } catch (requestError) {
    ElMessage.error(requestError?.message || '令牌刷新失败。');
  } finally {
    actionKey.value = '';
  }
}

async function revoke(row) {
  if (!canRevoke.value) return ElMessage.error('当前角色没有撤销授权的权限。');
  try { await ElMessageBox.confirm('撤销后相关同步任务将不能继续读取平台数据，确认继续？', '撤销授权', { type: 'error', confirmButtonText: '确认撤销' }); } catch { return; }
  actionKey.value = `revoke:${row.id}`;
  try {
    const response = await revokeStoreAuthorization(row.id);
    if (!response?.success) return ElMessage.error(response?.message || '授权撤销失败。');
    ElMessage.success('授权已撤销。');
    await load();
  } catch (requestError) {
    ElMessage.error(requestError?.message || '授权撤销失败。');
  } finally {
    actionKey.value = '';
  }
}

async function copyOAuthUrl() {
  if (!oauthUrl.value || copying.value) return;
  copying.value = true;
  try { await navigator.clipboard.writeText(oauthUrl.value); ElMessage.success('授权地址已复制。'); }
  catch { ElMessage.warning('浏览器未允许复制，请手动选择地址。'); }
  finally { copying.value = false; }
}

watch(() => route.query.platform, (value) => {
  const platform = normalizePlatform(value);
  if (platform === filters.platform) return;
  filters.platform = platform;
  oauthForm.platform = platform || 'shopee';
  page.value = 1;
  load();
});

onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.toolbar .el-select { width: 150px; }
.toolbar .el-input { width: 150px; }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.pagination :deep(.el-pagination) { margin-left: auto; }
.page-alert { margin-bottom: 14px; }
.oauth-form { margin-top: 18px; }
.oauth-form :deep(.el-form-item) { margin-bottom: 14px; }
.oauth-result { margin-top: 18px; }
.drawer-note { color: #64748b; line-height: 1.6; }
small { color: #64748b; }
@media (max-width: 760px) { .pagination { align-items: flex-start; flex-direction: column; } .pagination :deep(.el-pagination) { margin-left: 0; } }
</style>
