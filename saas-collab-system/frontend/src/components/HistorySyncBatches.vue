<template>
  <section class="history-batches" aria-label="Shopee 历史数据补采">
    <header><div><h2>Shopee 历史补采</h2><p>可同时选择多个店铺和数据类型，系统自动拆分为最多 15 天的批次。</p></div>
      <div class="actions"><el-button v-if="canManage" type="primary" @click="openCreate">创建历史同步</el-button><el-button :loading="loading" @click="load">刷新</el-button></div>
    </header>
    <el-alert type="warning" :closable="false" show-icon title="平台可能不会保留所选日期的全部数据；进度表示已处理的分段，不代表历史覆盖完整。" />
    <el-empty v-if="!loading && !batches.length" description="暂无历史同步批次" />
    <article v-for="batch in batches" :key="batch.id" class="batch">
      <div class="batch-heading"><div><strong>{{ batch.name || `历史同步 #${batch.id}` }}</strong><small>{{ batch.start_date }} 至 {{ batch.end_date }} · {{ statusText(batch.status) }}</small></div>
        <div v-if="canManage" class="actions">
          <el-button v-if="batch.status === 'running'" size="small" :loading="busy === `${batch.id}:pause`" :disabled="!!busy" @click="act(batch,'pause')">暂停</el-button>
          <el-button v-if="batch.status === 'paused'" size="small" :loading="busy === `${batch.id}:resume`" :disabled="!!busy" @click="act(batch,'resume')">继续</el-button>
          <el-button v-if="batch.failed_segments > 0" size="small" type="warning" :loading="busy === `${batch.id}:retry_failed`" :disabled="!!busy" @click="act(batch,'retry_failed')">重试失败分段</el-button>
        </div>
      </div>
      <el-progress :percentage="percent(batch.success_segments + batch.failed_segments, batch.total_segments)" :status="batch.failed_segments ? 'exception' : undefined" />
      <small>分段 {{ batch.success_segments || 0 }} 成功 / {{ batch.failed_segments || 0 }} 失败 / {{ batch.total_segments || 0 }} 总计 · 已获取 {{ batch.fetched_count || 0 }} 条</small>
      <div class="shops">
        <div v-for="shop in batch.shops || []" :key="shop.job_id" class="shop"><div><strong>{{ shop.shop_name }} · {{ resourceLabel(shop.resource_type) }}</strong><span>{{ statusText(shop.status) }}</span></div>
          <el-progress :percentage="percent((shop.success_segments || 0) + (shop.failed_segments || 0), shop.total_segments)" :status="shop.failed_segments ? 'exception' : undefined" />
          <small>{{ shop.success_segments || 0 }}/{{ shop.total_segments || 0 }} 分段 · {{ shop.fetched_count || 0 }} 条</small><p v-if="shop.last_error" class="error">{{ shop.last_error }}</p>
        </div>
      </div>
    </article>

    <el-dialog v-model="dialog" title="创建 Shopee 历史补采" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="批次名称"><el-input v-model="form.name" maxlength="100" placeholder="可选" /></el-form-item>
        <el-form-item label="店铺与数据类型（可多选）"><el-select v-model="form.job_ids" multiple filterable style="width:100%" placeholder="选择已启用的 Shopee 同步任务"><el-option v-for="job in eligibleJobs" :key="job.id" :value="job.id" :label="`${job.shop_name} · ${resourceLabel(job.resource_type)}`" /></el-select><small v-if="missingResourceTypes.length" class="missing-types">尚未找到以下类型的可用任务：{{ missingResourceTypes.map(resourceLabel).join('、') }}。请先创建对应同步任务。</small></el-form-item>
        <div class="dates"><el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item><el-form-item label="结束日期（含）"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item></div>
        <el-alert type="warning" :closable="false" title="日期按北京时间理解且包含结束日；平台可能无法提供所有历史日期的数据。" />
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="busy==='create'" :disabled="!canManage || !validForm || !!busy" @click="create">确认开始</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { actOnHistorySyncBatch, createHistorySyncBatch, fetchHistorySyncBatches } from '../api/integrations';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const canView = computed(() => auth.hasPermission('integrations.history.view'));
const canManage = computed(() => auth.hasPermission('integrations.history.manage') && auth.hasPermission('integrations.run_live_readonly'));
const batches = ref([]), jobs = ref([]), loading = ref(false), busy = ref(''), dialog = ref(false), timer = ref(null);
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const form = reactive({ name: '', job_ids: [], start_date: '', end_date: '' });
let submittedRequest = null;
function disableFutureDate(date) { return date.getTime() > new Date(`${today}T23:59:59+08:00`).getTime(); }
const resourceTypes = ['sales_order', 'refund_return', 'settlement_bill'];
const resourceLabels = { sales_order: '销售订单', refund_return: '退货退款', settlement_bill: '财务流水' };
function resourceLabel(value) { return resourceLabels[value] || value || '未知类型'; }
const eligibleJobs = computed(() => jobs.value.filter(job => job.is_enabled && !job.blocked_reason && resourceTypes.includes(job.resource_type)));
const missingResourceTypes = computed(() => resourceTypes.filter(type => !eligibleJobs.value.some(job => job.resource_type === type)));
const validForm = computed(() => form.job_ids.length > 0 && form.job_ids.length <= 100 && form.start_date && form.end_date && form.start_date <= form.end_date && form.end_date <= today);
function percent(done, total) { return total ? Math.min(100, Math.round(done * 100 / total)) : 0; }
function statusText(status) { return ({ running:'运行中', queued:'排队中', paused:'已暂停', completed:'已完成', failed:'失败', partial:'部分失败', pending:'待处理' })[status] || status || '未知'; }
async function load() {
  if (!canView.value) return;
  loading.value = true;
  try { const r = await fetchHistorySyncBatches(); if (!r?.success) throw new Error(r?.message || '历史同步读取失败'); batches.value = r.data?.batches || []; jobs.value = r.data?.jobs || []; updateTimer(); }
  catch (e) { ElMessage.error(e?.message || '历史同步读取失败'); }
  finally { loading.value = false; }
}
function openCreate() { if (!canManage.value) return; submittedRequest = null; form.name = ''; form.job_ids = []; form.start_date = ''; form.end_date = ''; dialog.value = true; }
async function create() {
  if (!canManage.value || !validForm.value || busy.value) return;
  try { await ElMessageBox.confirm(`将为 ${form.job_ids.length} 个店铺数据任务创建 ${form.start_date} 至 ${form.end_date}（含） 的只读历史补采。平台可能不保留全部日期。继续？`, '确认开始历史补采', { type:'warning' }); }
  catch { return; }
  busy.value = 'create';
  try {
    const payload = { name: form.name.trim(), job_ids: [...form.job_ids], start_date: form.start_date, end_date: form.end_date };
    const signature = JSON.stringify(payload);
    if (!submittedRequest || submittedRequest.signature !== signature) submittedRequest = { signature, key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
    const r = await createHistorySyncBatch({ ...payload, idempotency_key: submittedRequest.key }); if (!r?.success) throw new Error(r?.message || '提交失败'); ElMessage.success('历史同步已提交'); dialog.value = false; await load();
  }
  catch (e) { ElMessage.error(e?.message || '历史同步提交失败'); }
  finally { busy.value = ''; }
}
async function act(batch, action) {
  if (!canManage.value || busy.value) return;
  if (action === 'retry_failed') { try { await ElMessageBox.confirm(`将重试批次“${batch.name || batch.id}”中失败的分段。继续？`, '确认重试', { type:'warning' }); } catch { return; } }
  busy.value = `${batch.id}:${action}`;
  try { const r = await actOnHistorySyncBatch(batch.id, action); if (!r?.success) throw new Error(r?.message || '操作失败'); ElMessage.success('操作已提交'); await load(); }
  catch (e) { ElMessage.error(e?.message || '操作失败'); }
  finally { busy.value = ''; }
}
function updateTimer() {
  const active = batches.value.some(b => ['running','queued'].includes(b.status));
  if (active && !timer.value) timer.value = globalThis.setInterval(load, 10000);
  if (!active && timer.value) { globalThis.clearInterval(timer.value); timer.value = null; }
}
onMounted(load);
onUnmounted(() => { if (timer.value) globalThis.clearInterval(timer.value); });
</script>

<style scoped>
.history-batches{margin:0 0 24px;padding:18px;border:1px solid #dbe3ec;border-radius:10px;background:#fff}.history-batches header,.batch-heading,.batch-heading>div,.shop>div:first-child,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.history-batches h2{margin:0;font-size:18px}.history-batches header p,.batch small,.batch-heading small{display:block;color:#64748b;font-size:12px}.history-batches header p{margin:5px 0 12px}.batch{padding:16px 0;border-bottom:1px solid #e2e8f0}.batch:last-child{border-bottom:0}.batch-heading{margin-bottom:10px}.batch-heading small{margin-top:4px}.shops{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px}.shop{padding:12px;border:1px solid #e2e8f0;border-radius:8px}.shop>div:first-child span{color:#64748b;font-size:12px}.missing-types{display:block;margin-top:5px;color:#b45309;line-height:1.5}.error{margin:6px 0 0;color:#b91c1c;font-size:12px;overflow-wrap:anywhere}.dates{display:grid;grid-template-columns:1fr 1fr;gap:12px}.dates :deep(.el-date-editor){width:100%}@media(max-width:640px){.history-batches header,.batch-heading{align-items:flex-start;flex-direction:column}.actions{flex-wrap:wrap}}
</style>
