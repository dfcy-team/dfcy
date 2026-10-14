<template>
  <section class="finance-records"><h1>{{ title }}</h1><p>{{ note }}</p><el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form inline @submit.prevent="load"><el-form-item v-if="platformFilter" label="平台"><el-select v-model="filters.platform" clearable placeholder="全部"><el-option v-for="x in ['shopee','lazada','tiktok']" :key="x" :label="x" :value="x" /></el-select></el-form-item><el-form-item label="币种"><el-input v-model.trim="filters.currency" maxlength="3" clearable placeholder="如 USD" /></el-form-item><el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部"><el-option v-for="x in statuses" :key="x" :label="financeLabel(x)" :value="x" /></el-select></el-form-item><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></el-form>
    <el-table :data="rows" v-loading="loading" border :empty-text="error ? '读取失败，请重试' : '暂无记录，请通过财务导入登记真实资料'"><el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" min-width="120"><template #default="{ row }">{{ financeLabel(row[column.prop]) }}</template></el-table-column>
      <el-table-column v-if="exceptions" label="处理" width="180"><template #default="{ row }"><el-button @click="router.push(`/finance/reconciliation/matches/${row.reconciliation_match}`)">查看匹配</el-button><el-button v-if="canResolve && row.status === 'open'" :disabled="loading || resolving" @click="resolve(row)">登记解决</el-button></template></el-table-column>
    </el-table>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { resolveReconciliationException } from '../../api/financeReconciliation';
import { financeError, financeLabel } from './financePresentation';
const props = defineProps({ title: String, note: String, loader: Function, columns: Array, statuses: Array, platformFilter: { type: Boolean, default: true }, exceptions: Boolean });
const auth = useAuthStore(), router = useRouter(), filters = reactive({ platform: '', currency: '', status: '' }), rows = ref([]), error = ref(''), loading = ref(false), resolving = ref(false);
const canResolve = computed(() => auth.hasPermission('finance.exception.handle'));
let sequence = 0;
async function load() { const current = ++sequence; loading.value = true; error.value = ''; rows.value = []; try { const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value).map(([key, value]) => [key, key === 'currency' ? value.toUpperCase() : value])); const response = await props.loader(params); if (current !== sequence) return; if (!response.success) throw new Error(financeError(response)); rows.value = Array.isArray(response.data) ? response.data : response.data?.items || []; } catch (e) { if (current === sequence) error.value = e.message; } finally { if (current === sequence) loading.value = false; } }
function reset() { Object.assign(filters, { platform: '', currency: '', status: '' }); load(); }
async function resolve(row) { let value; try { ({ value } = await ElMessageBox.prompt('先拒绝错误匹配并核实资料，再记录解决说明。', '登记异常解决', { inputPattern: /\S/, inputErrorMessage: '请填写解决说明' })); } catch { return; } resolving.value = true; try { const response = await resolveReconciliationException(row.id, value.trim()); if (!response.success) throw new Error(financeError(response)); ElMessage.success('已记录异常处理'); await load(); } catch (e) { error.value = e.message; } finally { resolving.value = false; } }
onMounted(load);
</script>
<style scoped>.finance-records { display:grid; gap:16px; }.finance-records h1,.finance-records p { margin:0; }.finance-records .el-select { width:150px; }</style>
