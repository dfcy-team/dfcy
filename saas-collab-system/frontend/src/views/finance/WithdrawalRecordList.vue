<template>
  <section class="wallet-page" aria-labelledby="wallet-title">
    <header class="wallet-header">
      <div><h1 id="wallet-title">平台余额与提款记录</h1><p>当前用户可见店铺的平台 API 数据，按平台、店铺和原币核对。</p></div>
      <div class="wallet-actions"><el-button :loading="loading" @click="load">刷新本地显示</el-button><el-button v-if="canSync" type="primary" :disabled="busy" :loading="submitting" @click="synchronize">手动同步</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="message" role="status">{{ message }}</p>
    <section class="wallet-section" aria-labelledby="balance-title">
      <h2 id="balance-title">店铺余额</h2>
      <p class="wallet-note">余额类型与币种以接口为准。未获取不等于零，不以结算金额、广告余额或流水净额代替可提款余额。</p>
      <el-table :data="filteredStores" v-loading="loading" :empty-text="error ? '读取失败，请重试' : '当前权限范围内暂无店铺'" row-key="store_id" max-height="420">
        <el-table-column label="平台" min-width="110"><template #default="{ row }">{{ platformName(row.platform) }}</template></el-table-column>
        <el-table-column label="店铺" min-width="180"><template #default="{ row }">{{ row.store_name }}<small>{{ row.store_code }}</small></template></el-table-column>
        <el-table-column label="余额／原币" min-width="150"><template #default="{ row }">{{ row.balance == null ? '未获取' : `${row.balance} ${row.currency || ''}` }}</template></el-table-column>
        <el-table-column label="接口能力与口径" min-width="340"><template #default="{ row }"><p>{{ row.balance_note }}</p><p>{{ row.withdrawal_capability?.note }}</p></template></el-table-column>
        <el-table-column label="最近成功同步（UTC）" min-width="180"><template #default="{ row }">{{ utc(row.last_success_at) }}<small v-if="row.last_error_code">{{ syncError(row.last_error_code) }}</small></template></el-table-column>
      </el-table>
    </section>
    <section class="wallet-section" aria-labelledby="schedule-title">
      <h2 id="schedule-title">同步设置</h2>
      <p class="wallet-note">同步全部可同步店铺，不受下方记录筛选影响。只读采集，不发起提款、不刷新店铺授权、不补采历史。首次请求或启用时建立增量起点，首次同步可能没有新记录。</p>
      <dl class="wallet-sync-status"><div><dt>任务状态</dt><dd>{{ stateName(sync.state) }}</dd></div><div><dt>增量起点（UTC）</dt><dd>{{ utc(sync.activated_at) }}</dd></div><div><dt>下次执行（UTC）</dt><dd>{{ utc(sync.next_run_at) }}</dd></div></dl>
      <p v-if="sync.last_error_code" class="wallet-warning" role="status">{{ syncError(sync.last_error_code) }}</p>
      <el-form v-if="canSync" inline @submit.prevent="saveSchedule">
        <el-form-item label="定时同步"><el-switch v-model="schedule.enabled" aria-label="启用定时同步" @change="scheduleDirty = true" /></el-form-item>
        <el-form-item label="间隔（分钟）"><el-input-number v-model="schedule.interval_minutes" :min="15" :max="1440" :step="15" aria-label="同步间隔（分钟）" @change="scheduleDirty = true" /></el-form-item>
        <el-button native-type="submit" :loading="saving">保存同步设置</el-button>
      </el-form>
      <p v-else class="wallet-note">当前为只读查看；同步需财务导入及平台只读采集权限。</p>
    </section>
    <section class="wallet-section" aria-labelledby="withdrawals-title">
      <h2 id="withdrawals-title">平台 API 提款记录</h2>
      <p class="wallet-note">保留原始金额符号，提款退回单独标记。未返回的手续费、实际到账或到账时间不推算，也不认定银行已到账。</p>
      <el-form inline @submit.prevent="search">
        <el-form-item label="平台"><el-select v-model="filters.platform" clearable placeholder="全部平台" @change="filters.store_id = ''"><el-option v-for="value in platforms" :key="value" :label="platformName(value)" :value="value" /></el-select></el-form-item>
        <el-form-item label="店铺"><el-select v-model="filters.store_id" clearable filterable placeholder="全部可见店铺"><el-option v-for="store in filteredStores" :key="store.store_id" :label="`${store.store_name}（${store.store_code}）`" :value="store.store_id" /></el-select></el-form-item>
        <el-form-item label="原币"><el-input v-model.trim="filters.currency" maxlength="3" clearable placeholder="例如 PHP" /></el-form-item>
        <el-form-item label="平台状态"><el-input v-model.trim="filters.status" clearable placeholder="如 PROCESSING" /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button>
      </el-form>
      <el-table :data="records" v-loading="recordsLoading" :empty-text="error ? '读取失败，请重试' : '暂无已同步的 API 提款记录；不显示旧导入或手工登记数据'" row-key="id">
        <el-table-column label="平台／店铺" min-width="200"><template #default="{ row }">{{ platformName(row.platform) }} · {{ row.store_name }}<small>{{ row.store_code }}</small></template></el-table-column>
        <el-table-column prop="withdrawal_no" label="平台交易编号" min-width="230" />
        <el-table-column label="交易类型" min-width="160"><template #default="{ row }">{{ typeName(row.transaction_type) }}</template></el-table-column>
        <el-table-column label="原始交易金额" min-width="160"><template #default="{ row }">{{ row.amount }} {{ row.currency }}</template></el-table-column>
        <el-table-column label="平台原始状态" min-width="160"><template #default="{ row }">{{ row.status || '接口未返回' }}</template></el-table-column>
        <el-table-column label="交易时间（UTC）" min-width="185"><template #default="{ row }">{{ utc(row.occurred_at_utc) }}</template></el-table-column>
        <el-table-column label="来源／采集时间" min-width="240"><template #default="{ row }">平台 API<small>{{ row.source_endpoint }}</small><small>{{ utc(row.observed_at_utc) }}</small></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="loadRecords" />
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { fetchPlatformWallet, fetchApiWithdrawals, syncPlatformWallet, saveWalletSchedule } from '../../api/financeReconciliation';

const stores = ref([]), records = ref([]), sync = ref({ state: 'idle' });
const loading = ref(false), submitting = ref(false), saving = ref(false), canSync = ref(false);
const recordsLoading = ref(false), scheduleDirty = ref(false);
const error = ref(''), message = ref(''), page = ref(1), total = ref(0);
const filters = reactive({ platform: '', store_id: '', currency: '', status: '' });
const schedule = reactive({ enabled: false, interval_minutes: 60 });
const filteredStores = computed(() => stores.value.filter(store => !filters.platform || store.platform === filters.platform));
const platforms = computed(() => [...new Set(stores.value.map(store => store.platform))]);
const busy = computed(() => ['queued', 'running'].includes(sync.value.state));
let overviewSequence = 0, recordsSequence = 0, poll;
const platformName = value => ({ shopee: 'Shopee', lazada: 'Lazada', tiktok: 'TikTok Shop' })[value] || value;
const stateName = value => ({ idle: '尚未同步', queued: '排队中', running: '同步中', succeeded: '已完成本次同步', partial: '部分店铺未完成，请查看提示', failed: '同步失败', blocked: '权限已变化，任务已暂停', unsupported: '当前店铺接口尚未验收', no_visible_stores: '当前无可同步店铺' })[value] || value;
const typeName = value => ({ WITHDRAW: '提款', REVERSE: '提款退回', 'Auto Withdrawal': '自动提款', 'Manual Withdrawal': '手动提款' })[value] || value;
const syncError = value => ({ BROKER_UNAVAILABLE: '任务队列暂不可用，请检查后台同步服务。', PERMISSION_CHANGED: '同步权限发生变化，未继续采集。', STORE_API_SYNC_FAILED: '平台读取未成功，请检查授权及接口权限。', LAZADA_TIMEZONE_OR_API_NOT_VERIFIED: 'Lazada 时区口径或接口调用尚未通过校验。', PARTIAL_OR_FAILED: '部分同步未成功，已有资料保留，请核对各店铺提示。' })[value] || '同步暂未完成，请检查接入状态。';
function utc(value) {
  if (!value) return '尚无';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间待核对' : date.toISOString().slice(0, 19).replace('T', ' ');
}
function params() { return Object.fromEntries(Object.entries({ ...filters, currency: filters.currency.toUpperCase(), page: page.value, page_size: 20 }).filter(([, value]) => value !== '')); }
async function loadRecords() {
  const current = ++recordsSequence;
  recordsLoading.value = true;
  records.value = [];
  try {
    const result = await fetchApiWithdrawals(params());
    if (current !== recordsSequence) return;
    if (!result.success || !Array.isArray(result.data?.items)) throw new Error();
    records.value = result.data.items;
    total.value = result.data.pagination.total;
  } catch { if (current === recordsSequence) { total.value = 0; error.value = '提款记录读取失败，请重试；失败不代表没有提款记录。'; } }
  finally { if (current === recordsSequence) recordsLoading.value = false; }
}
async function load() {
  const current = ++overviewSequence;
  clearTimeout(poll);
  loading.value = true; error.value = '';
  try {
    const result = await fetchPlatformWallet();
    if (current !== overviewSequence) return;
    if (!result.success || !Array.isArray(result.data?.stores)) throw new Error();
    stores.value = result.data.stores; sync.value = result.data.sync; canSync.value = result.data.can_sync;
    if (!saving.value && !scheduleDirty.value) Object.assign(schedule, { enabled: sync.value.enabled, interval_minutes: sync.value.interval_minutes });
    await loadRecords();
    if (current === overviewSequence && busy.value) poll = setTimeout(load, 5000);
  } catch { if (current === overviewSequence) { stores.value = []; records.value = []; error.value = '平台余额与同步状态读取失败，请重试。'; } }
  finally { if (current === overviewSequence) loading.value = false; }
}
async function synchronize() {
  submitting.value = true; message.value = ''; error.value = '';
  try {
    const result = await syncPlatformWallet();
    if (!result.success) throw new Error();
    message.value = result.data.message; await load();
  } catch { error.value = '同步请求未能确认，请刷新任务状态后再操作，勿重复提交。'; }
  finally { submitting.value = false; }
}
async function saveSchedule() {
  saving.value = true; error.value = '';
  try {
    const result = await saveWalletSchedule({ ...schedule });
    if (!result.success) throw new Error();
    sync.value = result.data;
    scheduleDirty.value = false;
    message.value = schedule.enabled ? '定时同步已启用，将按当前权限执行，不补采历史。' : '定时同步已关闭。';
  } catch { error.value = '同步设置保存失败，请刷新核对。'; }
  finally { saving.value = false; }
}
function search() { page.value = 1; error.value = ''; loadRecords(); }
function reset() { Object.assign(filters, { platform: '', store_id: '', currency: '', status: '' }); search(); }
onMounted(load);
onBeforeUnmount(() => { ++overviewSequence; ++recordsSequence; clearTimeout(poll); });
</script>

<style scoped>
.wallet-page { display: grid; gap: 20px; }
.wallet-header, .wallet-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h1 { margin: 0 0 8px; font-size: 24px; } h2 { margin: 0 0 10px; font-size: 16px; }
p { margin: 6px 0; line-height: 1.6; font-size: 13px; }
.wallet-note, .wallet-header p { color: #475569; }
.wallet-section { min-width: 0; padding: 18px; background: #fff; border: 1px solid #dbe3ef; border-radius: 8px; }
small { display: block; margin-top: 4px; font-size: 12px; color: #475569; overflow-wrap: anywhere; }
.wallet-sync-status { display: flex; gap: 24px; flex-wrap: wrap; margin: 14px 0; }
dt { font-size: 12px; color: #475569; } dd { margin: 5px 0 0; font-size: 13px; }
.wallet-warning { color: #92400e; } .el-select { width: 190px; } .el-pagination { margin-top: 16px; }
@media (max-width: 600px) { .wallet-section { padding: 12px; } .wallet-actions { width: 100%; } .el-select { width: 100%; } }
</style>
