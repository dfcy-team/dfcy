<template>
  <section class="finance-match"><header><h1>对账匹配详情</h1><el-button @click="router.push('/finance/reconciliation/matches')">返回列表</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-if="loading" :rows="6" animated />
    <template v-else-if="match">
      <el-descriptions :column="2" border><el-descriptions-item v-for="field in fields" :key="field.prop" :label="field.label">{{ financeLabel(match[field.prop]) }}</el-descriptions-item></el-descriptions>
      <p>确认仅登记对账结果，不发起付款。差额不为零的匹配须先拒绝并核实资料；不能直接确认平账。</p>
      <div v-if="canReview && match.status === 'suggested' && !error"><el-button type="primary" :disabled="busy || Number(match.difference_amount) !== 0" @click="confirm">确认匹配</el-button><el-button type="danger" :disabled="busy" @click="reject">拒绝匹配</el-button></div>
    </template>
    <el-empty v-else-if="!error" description="暂无匹配详情" />
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { confirmReconciliationMatch, fetchReconciliationMatchDetail, rejectReconciliationMatch } from '../../api/financeReconciliation';
import { financeError, financeLabel } from './financePresentation';
const route = useRoute(), router = useRouter(), auth = useAuthStore(), match = ref(null), error = ref(''), loading = ref(false), busy = ref(false);
const canReview = computed(() => auth.hasPermission('finance.reconcile'));
const fields = [{prop:'id',label:'匹配编号'},{prop:'platform',label:'平台'},{prop:'currency',label:'币种'},{prop:'statement_no',label:'账单编号'},{prop:'withdrawal_no',label:'提现编号'},{prop:'receipt_reference',label:'到账参考编号'},{prop:'statement_net_amount',label:'账单净额'},{prop:'withdrawal_expected_amount',label:'预计到账'},{prop:'receipt_amount',label:'银行到账金额'},{prop:'match_type',label:'匹配类型'},{prop:'matched_amount',label:'匹配金额'},{prop:'difference_amount',label:'差异金额'},{prop:'status',label:'状态'},{prop:'reviewed_by_id',label:'复核人 ID'},{prop:'reviewed_at',label:'复核时间'}];
let sequence = 0;
async function load() {
  const current = ++sequence, id = String(route.params.id || ''); match.value = null; error.value = ''; loading.value = true;
  try { if (!/^[1-9]\d*$/.test(id)) throw new Error('匹配编号无效。'); const response = await fetchReconciliationMatchDetail(id); if (current !== sequence) return; if (!response.success) throw new Error(financeError(response)); if (!response.data || Array.isArray(response.data) || String(response.data.id) !== id) throw new Error('匹配详情与当前编号不一致，已禁止复核。'); match.value = response.data; } catch(e) { if (current === sequence) error.value = e.message; } finally { if (current === sequence) loading.value = false; }
}
async function review(action) {
  if (!match.value || busy.value || loading.value || error.value || match.value.status !== 'suggested' || !canReview.value) return;
  const id = match.value.id;
  if (String(id) !== String(route.params.id)) return;
  let reason;
  try { if (action === 'confirm') await ElMessageBox.confirm('已核对这组账单、提现及到账记录，确认登记为已匹配？', '确认对账'); else ({ value: reason } = await ElMessageBox.prompt('请说明拒绝原因。原始账单、提现及到账资料会保留。', '拒绝匹配', { inputPattern: /\S/, inputErrorMessage: '请填写拒绝原因' })); } catch { return; }
  if (String(id) !== String(route.params.id) || match.value?.id !== id || error.value || loading.value) return;
  busy.value = true;
  try { const response = action === 'confirm' ? await confirmReconciliationMatch(id) : await rejectReconciliationMatch(id, reason.trim()); if (!response.success) throw new Error(financeError(response)); ElMessage.success(action === 'confirm' ? '已确认匹配' : '已拒绝匹配'); await load(); } catch(e) { error.value = e.message; match.value = null; } finally { busy.value = false; }
}
const confirm = () => review('confirm'), reject = () => review('reject');
watch(() => route.params.id, load, { immediate: true });
</script>
<style scoped>.finance-match{display:grid;gap:16px}.finance-match header{display:flex;align-items:center;justify-content:space-between}.finance-match h1,.finance-match p{margin:0}</style>
