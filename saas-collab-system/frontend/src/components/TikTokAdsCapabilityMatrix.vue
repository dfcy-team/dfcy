<template>
  <section aria-label="TK 广告能力矩阵" v-loading="loading">
    <el-alert title="ADVERTISING · TK 广告：仅采集 BASIC / AUCTION_CAMPAIGN 竞价广告消耗，不代表全部广告花费或 GMV Max。读取开关不会启用任务。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="ads-toolbar">
      <el-select v-model="selectedStoreId" filterable placeholder="选择已绑定广告户的店铺" aria-label="TK 广告店铺">
        <el-option v-for="store in stores" :key="store.id" :value="store.id" :label="`${store.code} · ${store.name}`" />
      </el-select>
      <el-button :disabled="loading || Boolean(busy)" @click="load">刷新广告能力</el-button>
    </div>
    <el-table :data="visibleItems" row-key="mapping_id" border stripe empty-text="暂无广告户；请先到店铺 API 接入完成 TK 广告授权和绑定">
      <el-table-column label="能力 / 广告户" min-width="220"><template #default="{ row }"><strong>ADVERTISING · 广告</strong><div>{{ row.advertiser_id }}</div></template></el-table-column>
      <el-table-column prop="config_name" label="广告 API 连接" min-width="180" />
      <el-table-column label="币种 / 数据时区" min-width="170"><template #default="{ row }">{{ row.currency || '未知' }}<div>{{ row.timezone || '未知' }}</div></template></el-table-column>
      <el-table-column label="读取" min-width="110"><template #default="{ row }">
        <el-switch :model-value="row.read_enabled" :disabled="!canAuthorize || Boolean(busy) || (!row.read_enabled && row.can_enable_read !== true)" :loading="busy === `read:${row.mapping_id}`" active-text="开启" inactive-text="关闭" @change="setRead(row, $event)" />
      </template></el-table-column>
      <el-table-column label="写入" width="85"><template #default><el-tag type="info">关闭</el-tag></template></el-table-column>
      <el-table-column label="账户核验 / 阻塞原因" min-width="230"><template #default="{ row }"><div>{{ row.verification_state === 'verified' ? '账户已验证' : '账户待核验' }}</div><small>{{ row.blocked_reason || '可配置只读采集任务' }}</small></template></el-table-column>
      <el-table-column label="任务状态" min-width="130"><template #default="{ row }">{{ row.existing_job_id ? (row.job_enabled ? '任务已启用' : '任务已停用') : '尚未创建任务' }}</template></el-table-column>
      <el-table-column label="最近真实成功" min-width="170"><template #default="{ row }">{{ row.last_success_at ? syncBeijingTime(row.last_success_at) : '尚未成功采集' }}</template></el-table-column>
      <el-table-column label="操作" min-width="175"><template #default="{ row }">
        <el-button v-if="row.existing_job_id" link type="primary" @click="openJob(row.existing_job_id)">查看任务与定时</el-button>
        <el-button v-else :disabled="!canManage || Boolean(busy) || !row.read_enabled || Boolean(row.blocked_reason)" :loading="busy === `create:${row.mapping_id}`" @click="createJob(row)">创建同步任务</el-button>
      </template></el-table-column>
    </el-table>
    <p class="ads-note">一家店可有多个广告户，每户独立任务。先执行一次真实同步并核对金额，再在任务中保存定时计划、启用定时。不同币种不能直接相加。</p>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { createSyncJob } from '../api/integrations';
import { fetchAdsCapabilities, updateAdsReadCapability } from '../api/tiktokAds';
import { syncBeijingTime, syncError } from '../utils/syncPresentation';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const canAuthorize = computed(() => auth.hasPermission('integrations.store.authorize'));
const canManage = computed(() => auth.hasPermission('integrations.manage'));
const loading = ref(false), busy = ref(''), error = ref(''), items = ref([]);
const selectedStoreId = ref(Number(route.query.store_id) || null);
let generation = 0;
const stores = computed(() => [...new Map(items.value.map(row => [row.store_id, {
  id: row.store_id, code: row.store_code, name: row.store_name,
}])).values()]);
const visibleItems = computed(() => items.value.filter(row => row.store_id === selectedStoreId.value));
async function load() {
  const version = ++generation;
  loading.value = true; error.value = '';
  try {
    const response = await fetchAdsCapabilities();
    if (version !== generation) return;
    if (!response?.success) throw new Error(response?.message || '读取 TK 广告能力失败');
    items.value = response.data.items || [];
    if (!stores.value.some(store => store.id === selectedStoreId.value)) selectedStoreId.value = stores.value[0]?.id || null;
  } catch (reason) {
    if (version === generation) { items.value = []; error.value = syncError(reason.message); }
  } finally { if (version === generation) loading.value = false; }
}
async function setRead(row, enabled) {
  if (!canAuthorize.value || busy.value || (!row.read_enabled && row.can_enable_read !== true)) return;
  const storeId = selectedStoreId.value;
  try { await ElMessageBox.confirm(`${enabled ? '允许' : '关闭'}广告户 ${row.advertiser_id} 的只读采集？不会启用任务或修改平台数据。`, 'TK 广告读取能力'); } catch { return; }
  if (!canAuthorize.value || busy.value || storeId !== selectedStoreId.value) return;
  busy.value = `read:${row.mapping_id}`;
  try {
    const response = await updateAdsReadCapability(row.mapping_id, enabled);
    if (!response?.success) throw new Error(response?.message || '保存读取能力失败');
    await load();
  } catch (reason) { error.value = syncError(reason.message); }
  finally { busy.value = ''; }
}
function openJob(id) { router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: id } }); }
async function createJob(row) {
  if (!canManage.value || busy.value || row.existing_job_id || !row.read_enabled || row.blocked_reason) return;
  const storeId = selectedStoreId.value;
  try { await ElMessageBox.confirm(`为广告户 ${row.advertiser_id} 创建一个手动、停用的竞价广告消耗任务？不会立即采集。`, '创建 TK 广告任务'); } catch { return; }
  if (!canManage.value || busy.value || storeId !== selectedStoreId.value) return;
  busy.value = `create:${row.mapping_id}`;
  try {
    const response = await createSyncJob({ integration_config_id: row.integration_config_id, ads_mapping_id: row.mapping_id,
      resource_type: 'advertising_report', schedule_type: 'manual', is_enabled: false, execution_mode: 'live_readonly',
      query_mode: 'incremental', lookback_days: 7 });
    if (!response?.success) throw new Error(response?.message || '创建任务失败');
    ElMessage.success('广告任务已创建，保持手动、停用；尚未采集数据。');
    await load();
  } catch (reason) { error.value = syncError(reason.message); }
  finally { busy.value = ''; }
}
defineExpose({ load });
onMounted(load);
onBeforeUnmount(() => { generation += 1; });
</script>
<style scoped>
.ads-toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.ads-toolbar .el-select { width: min(440px, 100%); }
.ads-note, small { color: #64748b; font-size: 13px; line-height: 1.7; }
.el-alert { margin-bottom: 12px; }
</style>
