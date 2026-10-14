<template>
  <section class="finance-import">
    <h1>财务导入</h1>
    <p>导入平台账单、已完成提现及银行到账资料。只登记财务记录，不发起付款或银行操作。</p>
    <el-alert title="使用 UTF-8 CSV 模板，每批最多 500 条、1 MB。银行账号仅接受 **** 加最多四位尾号；提现时间须含时区，如 2026-10-01T08:00:00+08:00。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" @submit.prevent="previewFile">
      <el-form-item label="资料类型"><el-select v-model="kind" :disabled="busy" @change="clearPreview"><el-option v-for="item in kinds" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
      <el-button :disabled="!templates[kind] || busy" @click="downloadTemplate">下载 CSV 模板</el-button>
      <el-form-item label="CSV 文件"><input ref="fileInput" type="file" accept=".csv,text/csv" :disabled="busy" @change="chooseFile" /></el-form-item>
      <el-button type="primary" native-type="submit" :disabled="!file || busy" :loading="busy">预检文件</el-button>
      <el-button type="success" :disabled="!preview || busy || preview.new_rows === 0" @click="commitFile">确认导入 {{ preview?.new_rows ?? 0 }} 条新记录</el-button>
    </el-form>
    <section v-if="preview"><h2>预检通过</h2><p>共 {{ preview.rows }} 条，新增 {{ preview.new_rows }} 条，跳过 {{ preview.duplicate_rows }} 条完全相同的记录。预览最多显示 20 条。</p><el-table :data="preview.preview" border><el-table-column prop="reference" label="编号" /><el-table-column prop="platform" label="平台" /><el-table-column prop="currency" label="币种" /><el-table-column prop="amount" label="净额 / 预计到账 / 到账金额" /></el-table></section>
    <h2>我的导入记录</h2><el-table :data="history" border empty-text="暂无导入记录"><el-table-column prop="created_at" label="时间" /><el-table-column label="类型"><template #default="{ row }">{{ kinds.find(x => x.value === row.kind)?.label || row.kind }}</template></el-table-column><el-table-column prop="rows" label="总条数" /><el-table-column prop="created" label="新增" /><el-table-column prop="skipped" label="重复跳过" /></el-table>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { fetchFinanceImports, submitFinanceImport } from '../../api/financeImports';
import { financeError } from './financePresentation';
const kinds = [{ value: 'statements', label: '平台账单' }, { value: 'withdrawals', label: '已完成提现' }, { value: 'bank-receipts', label: '银行到账' }];
const kind = ref('statements'), file = ref(null), fileInput = ref(null), preview = ref(null), templates = ref({}), history = ref([]), error = ref(''), busy = ref(false);
function clearPreview() { preview.value = null; error.value = ''; }
function chooseFile(event) { file.value = event.target.files?.[0] || null; clearPreview(); }
async function loadHistory() { const response = await fetchFinanceImports(); if (!response.success) throw new Error(financeError(response)); templates.value = response.data.templates; history.value = response.data.history; }
function downloadTemplate() { const blob = new Blob(['\uFEFF' + templates.value[kind.value].join(',') + '\r\n'], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `finance-${kind.value}.csv`; link.click(); URL.revokeObjectURL(url); }
async function previewFile() {
  if (!file.value || busy.value) return;
  clearPreview(); busy.value = true;
  try { const response = await submitFinanceImport(kind.value, file.value); if (!response.success) throw new Error(financeError(response)); preview.value = response.data; } catch (e) { error.value = e.message; } finally { busy.value = false; }
}
async function commitFile() {
  if (!preview.value || !file.value || busy.value) return;
  try { await ElMessageBox.confirm(`新增 ${preview.value.new_rows} 条财务记录，重复记录会跳过，已有记录不会被覆盖。`, '确认导入'); } catch { return; }
  busy.value = true; error.value = '';
  try { const response = await submitFinanceImport(kind.value, file.value, 'commit', preview.value.sha256); if (!response.success) throw new Error(financeError(response)); preview.value = null; file.value = null; if (fileInput.value) fileInput.value.value = ''; ElMessage.success(`导入完成：新增 ${response.data.created} 条，跳过 ${response.data.skipped} 条`); await loadHistory(); } catch (e) { preview.value = null; error.value = e.message; } finally { busy.value = false; }
}
onMounted(async () => { try { await loadHistory(); } catch (e) { error.value = e.message; } });
</script>
<style scoped>.finance-import { display:grid; gap:16px; }.finance-import h1,.finance-import h2,.finance-import p { margin:0; }.finance-import form { max-width:760px; }.finance-import input { max-width:100%; }</style>
