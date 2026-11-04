<template>
  <el-card shadow="never" class="lazada-panel">
    <template #header>Lazada 只读接口 · {{ authorization?.store_code || '请先选择授权' }}</template>
    <el-alert title="使用已保存的原令牌，不刷新。查询结果保存为快照，不直接重复登记财务流水；平台写操作关闭。" type="info" :closable="false" />
    <div class="account-shortcuts">
      <el-button :disabled="busy || !hasAccountOperation" @click="selectAccount()">店铺资金流水</el-button>
      <el-button :disabled="busy || !hasAccountOperation" @click="selectAccount('Sponsored Solutions Top-up')">广告充值记录</el-button>
    </div>
    <el-form label-position="top" @submit.prevent="execute">
      <el-form-item label="查询接口">
        <el-select v-model="operationName" :disabled="busy" filterable style="width: 100%" @change="resetPayload">
          <el-option v-for="item in catalog" :key="item.name" :value="item.name" :disabled="item.enabled === false" :label="`${item.group} · ${item.label}`" />
        </el-select>
      </el-form-item>
      <p v-if="operation" class="contract">{{ operation.method }} {{ operation.path }}<br />必填：{{ operation.required.join('、') || '无' }}；可选：{{ operation.optional.join('、') || '无' }}</p>
      <p class="contract">所选店铺最近验证：{{ proof ? (proof.status === 'succeeded' ? '成功' : `失败（${proof.error_code}）`) : '尚未验证' }}</p>
      <template v-if="operationName === 'account_transactions'">
        <p class="contract">查询店铺账户收支；“广告充值”仅代表店铺资金转入广告的记录，不是广告钱包完整流水。接口不提供每笔交易后的余额，金额按原币保留、不跨币种合计。</p>
        <div class="account-filters">
          <el-form-item label="交易日期（店铺站点）" required><el-date-picker v-model="accountForm.dates" :disabled="busy" type="daterange" value-format="YYYYMMDD" start-placeholder="开始日期" end-placeholder="结束日期" aria-label="账户交易日期" /></el-form-item>
          <el-form-item label="交易类型"><el-select v-model="accountForm.transaction_type" clearable :disabled="busy" placeholder="全部类型" aria-label="账户交易类型"><el-option v-for="(label, value) in transactionTypes" :key="value" :value="value" :label="label" /></el-select></el-form-item>
          <el-form-item label="交易子类型"><el-select v-model="accountForm.sub_transaction_type" clearable :disabled="busy" placeholder="全部子类型" aria-label="账户交易子类型"><el-option v-for="(label, value) in transactionSubtypes" :key="value" :value="value" :label="label" /></el-select></el-form-item>
          <el-form-item label="交易编号"><el-input v-model="accountForm.transaction_number" clearable :disabled="busy" maxlength="191" placeholder="完整交易编号（可选）" /></el-form-item>
        </div>
      </template>
      <el-form-item v-else label="业务查询参数（JSON；不要填写令牌或密钥）">
        <el-input v-model="payloadText" type="textarea" :rows="6" :disabled="busy" />
      </el-form-item>
      <el-button type="primary" :disabled="!authorization || !operation" :loading="busy" @click="execute">执行一次只读查询</el-button>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="result">
      <p>快照 #{{ result.id }} · {{ result.status === 'succeeded' ? '调用成功（不代表全部页采集完成）' : `调用失败：${result.error_code}` }}</p>
      <template v-if="accountPage">
        <p class="contract" role="status">查询日期 {{ result.parameters.start_time }}—{{ result.parameters.end_time }} · 共 {{ accountPage.page_info.total_count }} 条 · 第 {{ accountPage.page_info.page_num }} 页，仅显示本页数据。</p>
        <el-table :data="accountPage.transactions" aria-label="Lazada店铺账户交易明细" empty-text="该查询范围暂无账户交易；可调整日期或类型后重试。" max-height="420">
          <el-table-column prop="transaction_number" label="交易编号" min-width="180" />
          <el-table-column prop="transaction_time" label="交易时间" min-width="170" />
          <el-table-column prop="type" label="类型" min-width="110" />
          <el-table-column prop="sub_type" label="子类型" min-width="210" />
          <el-table-column prop="amount" label="金额（原币）" min-width="150" align="right" />
          <el-table-column prop="currency" label="币种" width="80" />
          <el-table-column label="状态跟踪" min-width="190"><template #default="{ row }">{{ (row.tracking_list || []).map(item => item.status || item.name).filter(Boolean).join(' / ') || '—' }}</template></el-table-column>
          <el-table-column prop="remarks" label="备注" min-width="220" />
        </el-table>
        <div class="account-pagination"><el-button :disabled="busy || accountPage.page_info.page_num <= 1" @click="loadAccountPage(accountPage.page_info.page_num - 1)">上一页</el-button><el-button :disabled="busy || accountPage.page_info.page_num >= accountPage.page_info.total_page" @click="loadAccountPage(accountPage.page_info.page_num + 1)">下一页（查询平台）</el-button></div>
        <details><summary>查看原始查询快照</summary><pre class="response">{{ JSON.stringify(result.response, null, 2) }}</pre></details>
      </template>
      <pre v-else class="response">{{ JSON.stringify(result.response, null, 2) }}</pre>
    </template>
    <el-table :data="history" size="small" empty-text="所选店铺尚无接口验证快照">
      <el-table-column prop="id" label="快照" width="80" />
      <el-table-column prop="operation" label="接口" />
      <el-table-column prop="status" label="结果" />
      <el-table-column prop="error_code" label="受控错误码" />
      <el-table-column prop="created_at" label="查询时间" min-width="190" />
    </el-table>
    <p class="contract">订单、商品、售后、财务流水的正式入库仍使用同步任务；其他查询当前为原生快照。Webhook 尚未启用外网回调。</p>
  </el-card>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { fetchLazadaOperations, fetchLazadaReadHistory, executeLazadaRead } from '../api/integrations';

const props = defineProps({ authorization: { type: Object, default: null } });
const catalog = ref([]);
const operationName = ref('seller');
const operation = computed(() => catalog.value.find(item => item.name === operationName.value));
const payloadText = ref('{}');
const busy = ref(false);
const error = ref('');
const result = ref(null);
const history = ref([]);
const proof = computed(() => history.value.find(item => item.operation === operationName.value));
const hasAccountOperation = computed(() => catalog.value.some(item => item.name === 'account_transactions' && item.enabled !== false));
const accountForm = reactive({ dates: [], transaction_type: '', sub_transaction_type: '', transaction_number: '' });
const transactionTypes = { Deposit: '入账', Withdrawal: '提现', Payment: '支付' };
const transactionSubtypes = { Settlement: '结算', 'Failed Payment': '支付失败', 'Returned Payment': '支付退回',
  'Auto Withdrawal': '自动提现', 'Manual Withdrawal': '手动提现', 'Sponsored Solutions Top-up': '广告充值' };
const accountPage = computed(() => {
  if (result.value?.operation !== 'account_transactions' || result.value.status !== 'succeeded') return null;
  const data = result.value.response?.data;
  if (!data?.page_info || !Array.isArray(data.transactions)) return null;
  return { ...data, page_info: { ...data.page_info,
    total_page: Math.ceil(data.page_info.total_count / data.page_info.page_size) } };
});
let generation = 0;
onUnmounted(() => { generation += 1; });
function selectAccount(subtype = '') {
  if (busy.value || !hasAccountOperation.value) return;
  operationName.value = 'account_transactions';
  accountForm.transaction_type = '';
  accountForm.sub_transaction_type = subtype;
  accountForm.transaction_number = '';
  resetPayload();
}
function resetPayload() {
  payloadText.value = JSON.stringify(Object.fromEntries((operation.value?.required || []).map(key => [key, ''])), null, 2);
  result.value = null;
  error.value = '';
}
async function loadHistory(id, epoch) {
  if (!id) return;
  try {
    const response = await fetchLazadaReadHistory(id);
    if (!response.success) throw new Error('history failed');
    if (epoch === generation) history.value = response.data;
  } catch {
    if (epoch === generation) error.value = '读取验证历史失败，请检查权限。';
  }
}
watch(() => props.authorization?.id, id => {
  const epoch = ++generation;
  result.value = null;
  history.value = [];
  error.value = '';
  loadHistory(id, epoch);
}, { immediate: true });
onMounted(async () => {
  try {
    const response = await fetchLazadaOperations();
    if (!response.success) throw new Error('catalog failed');
    catalog.value = response.data.operations;
  }
  catch { error.value = '加载 Lazada 接口清单失败。'; }
});
async function execute() {
  if (busy.value || !props.authorization?.id || !operation.value || operation.value.enabled === false) return;
  error.value = '';
  let payload;
  if (operationName.value === 'account_transactions') {
    const dates = accountForm.dates;
    if (!Array.isArray(dates) || dates.length !== 2 || dates.some(value => !/^[0-9]{8}$/.test(value)) || dates[0] > dates[1]) {
      error.value = '请选择有效的交易日期，开始日期不能晚于结束日期。'; return;
    }
    payload = { start_time: dates[0], end_time: dates[1], page_num: 1, page_size: 20 };
    for (const key of ['transaction_type', 'sub_transaction_type', 'transaction_number']) {
      if (accountForm[key]?.trim()) payload[key] = accountForm[key].trim();
    }
  } else {
    try { payload = JSON.parse(payloadText.value); }
    catch { error.value = '查询参数不是有效 JSON。'; return; }
  }
  await read(operationName.value, payload);
}
async function loadAccountPage(number) {
  if (!accountPage.value || !Number.isInteger(number) || number < 1 || number > accountPage.value.page_info.total_page) return;
  await read('account_transactions', { ...result.value.parameters, page_num: number });
}
async function read(name, payload) {
  if (busy.value || !props.authorization?.id) return;
  const id = props.authorization.id;
  const epoch = generation;
  error.value = '';
  result.value = null;
  busy.value = true;
  try {
    const response = await executeLazadaRead(id, { operation: name, payload });
    if (!response.success) throw new Error('read failed');
    if (epoch === generation) { result.value = response.data; await loadHistory(id, epoch); }
  } catch { if (epoch === generation) error.value = '查询未完成：请检查授权有效期、权限和必填参数；系统不会尝试刷新。'; }
  finally { busy.value = false; }
}
</script>

<style scoped>
.lazada-panel { margin-top: 20px; }
.el-form { margin: 18px 0; }
.contract { font-size: 12px; color: #606266; line-height: 1.7; overflow-wrap: anywhere; }
.response { max-height: 420px; overflow: auto; background: #f5f7fa; padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.account-shortcuts, .account-pagination { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
.account-filters { display: flex; flex-wrap: wrap; gap: 16px; }
.account-filters .el-form-item { min-width: 200px; max-width: 100%; }
</style>
