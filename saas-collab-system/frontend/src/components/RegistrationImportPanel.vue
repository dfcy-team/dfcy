<template>
  <section class="registration-import" aria-label="批量登记">
    <ol class="import-steps"><li :class="{ active: !file }">下载对应模板</li><li :class="{ active: file && !preview }">选择文件并校验</li><li :class="{ active: preview }">{{ historical ? '核对后历史补录' : '核对后导入草稿' }}</li></ol>
    <el-checkbox v-if="kind === 'exchange'" v-model="historical" :disabled="busy || Boolean(preview?.confirmed)">历史补录（仅留档，不提交审批、不调整履约或库存）</el-checkbox>
    <el-alert v-if="historical" title="按原订单核对商品与数量，不要求订单当前待发货或换入商品具有当前店铺映射；记录直接保存为“历史已登记”，不可用于执行换货。请在备注填写原始发生日期和来源。" type="info" :closable="false" />
    <div class="import-heading"><div><h3>{{ title }}模板</h3><p>{{ guidance }}</p></div><el-button :disabled="busy" @click="downloadTemplate">下载xlsx模板</el-button></div>
    <p class="limits">XLSX ≤ 5MB，最多500行。<template v-if="kind === 'gcash'">ZIP ≤ 25MB、最多100个根目录文件。截图名称与表格一致，多张用英文分号分隔。</template><template v-else>无需截图或附件，仅上传登记表。</template></p>
    <div class="import-files">
      <label>登记表（xlsx，必选）<input :key="`sheet-${inputVersion}`" type="file" accept=".xlsx" :disabled="busy" @change="setFile($event, 'file')" /><small>{{ file ? `${file.name} · ${fileSize(file.size)}` : '请选择本页面对应的模板，不要混用其他登记类型。' }}</small></label>
      <label v-if="kind === 'gcash'">截图附件（ZIP根目录）<input :key="`zip-${inputVersion}`" type="file" accept=".zip" :disabled="busy" @change="setFile($event, 'attachments')" /><small>{{ attachments ? `${attachments.name} · ${fileSize(attachments.size)}` : 'GCash批量登记必须提供匹配的付款截图。' }}</small></label>
    </div>
    <div class="import-actions"><el-button type="primary" plain :disabled="!file || busy || (kind === 'gcash' && !attachments)" :loading="busy" @click="run(false)">校验预览（不导入）</el-button><el-button :disabled="busy || (!file && !attachments)" @click="reset">清除文件</el-button><span v-if="busy" role="status">正在校验或导入，请勿重复提交。</span></div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" role="alert" />
    <template v-if="preview">
      <div class="preview-summary" role="status"><strong>{{ preview.confirmed ? `导入批次 #${preview.batch_id}` : '校验结果（尚未导入）' }}</strong><span>共 {{ preview.results.length }} 张登记 · {{ validCount }} 张有效 · {{ errorCount }} 张有错 · {{ existingCount }} 张已存在</span></div>
      <el-table :data="preview.results" max-height="360" empty-text="没有可导入的登记">
        <el-table-column label="Excel行号" width="105"><template #default="{ row }">{{ row.rows.join(', ') }}</template></el-table-column>
        <el-table-column prop="group" label="分组号" min-width="110" />
        <el-table-column label="关联业务" min-width="170"><template #default="{ row }"><b>{{ row.store_code || '—' }}</b><small>{{ row.order_number || '未关联订单' }}</small></template></el-table-column>
        <el-table-column label="金额／商品变化" min-width="155"><template #default="{ row }">{{ row.payload?.cost || row.payload?.amount || (row.payload?.changes ? `${row.payload.changes.length}项变化` : '—') }} {{ row.payload?.currency || '' }}</template></el-table-column>
        <el-table-column v-if="kind === 'gcash'" label="附件" width="70"><template #default="{ row }">{{ row.attachment_count ?? '—' }}</template></el-table-column>
        <el-table-column label="结果" min-width="155"><template #default="{ row }"><el-tag :type="row.valid ? 'success' : 'danger'" effect="plain">{{ historical && row.status === 'created' ? '历史已登记' : resultLabels[row.status] || row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="error" label="错误原因" min-width="230" />
        <el-table-column label="登记" width="100"><template #default="{ row }"><el-button v-if="row.id && canView" link type="primary" @click="emit('open-record', row.id)">#{{ row.id }}</el-button><span v-else>{{ row.id || '—' }}</span></template></el-table-column>
      </el-table>
      <div class="import-actions"><el-button v-if="errorCount" @click="downloadErrors">下载错误清单</el-button><template v-if="!preview.confirmed"><el-checkbox v-if="errorCount" v-model="validOnly">仅导入有效登记，错误分组整张不导入</el-checkbox><el-button type="primary" :disabled="busy || !validCount || (!validOnly && errorCount > 0)" :loading="busy" @click="run(true)">{{ historical ? '确认历史补录（不执行换货）' : '确认导入草稿' }}</el-button></template><el-button v-else-if="canView" type="primary" plain @click="emit('view-batch', preview.batch_id)">{{ historical ? '查看本批次历史登记' : '查看本批次草稿' }}</el-button></div>
    </template>
    <p class="boundary">{{ historical ? '历史补录仅保存历史事实，不修改订单、待发货明细、库存或仓库数据。' : kind === 'exchange' ? '仅生成草稿，不自动审批或修改待发货明细。' : '仅生成草稿，尚未确认付款；核对实际付款后，另行确认已付款并登记。系统不会发起转账。' }}关闭窗口后可在“导入记录”查找已确认的批次；重试失败项须重新选择原文件并校验。</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { requestApi, downloadApiFile } from '../api/request';
const props = defineProps({ kind: { type: String, required: true }, canView: { type: Boolean, default: false } });
const emit = defineEmits(['imported', 'open-record', 'view-batch']);
const file = ref(null), attachments = ref(null), preview = ref(null), busy = ref(false), error = ref(''), validOnly = ref(false), inputVersion = ref(0);
const historical = ref(false);
let generation = 0;
const title = computed(() => ({ exchange: '换货登记', promotion: '订单推广登记', gcash: 'GCash退款登记' }[props.kind]));
const guidance = computed(() => ({ exchange: '同一分组可有多行商品变化；原因和备注必须一致。原SKU减少量以当前待发货数量为准。', promotion: '每张登记一行；跨币种填写汇率日期和来源。整单成本由服务端计算。', gcash: '每张登记一行；手机号和交易参考号按文本填写，付款日期使用YYYY-MM-DD，必须填写备注及匹配截图。' }[props.kind]));
const resultLabels = { preview: '通过，未导入', error: '错误，未导入', created: '已创建草稿', existing: '已存在，不重复创建' };
const validCount = computed(() => preview.value?.results.filter(row => row.valid).length || 0);
const errorCount = computed(() => preview.value?.results.filter(row => !row.valid).length || 0);
const existingCount = computed(() => preview.value?.results.filter(row => row.status === 'existing').length || 0);
const base = () => `/api/internal/commerce/registrations/${props.kind}/`;
const fileSize = size => size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.ceil(size / 1024)} KB`;
function reset() { generation++; file.value = null; attachments.value = null; preview.value = null; error.value = ''; validOnly.value = false; busy.value = false; inputVersion.value++; }
function setFile(event, field) {
  const selected = event.target.files?.[0] || null;
  preview.value = null; validOnly.value = false; error.value = '';
  const isSheet = field === 'file', target = isSheet ? file : attachments;
  target.value = null;
  if (selected && (!selected.name.toLowerCase().endsWith(isSheet ? '.xlsx' : '.zip') || selected.size > (isSheet ? 5 : 25) * 1048576)) {
    error.value = isSheet ? '请选择不超过5MB的xlsx登记模板。' : '请选择不超过25MB的ZIP截图附件。'; event.target.value = ''; return;
  }
  target.value = selected;
}
async function run(confirm) {
  if (busy.value) return;
  if (!file.value || (props.kind === 'gcash' && !attachments.value)) { error.value = '请先选择登记表及本类型要求的附件。'; return; }
  if (confirm && (!preview.value || preview.value.confirmed || !validCount.value || (!validOnly.value && errorCount.value))) return;
  const current = generation, url = base();
  busy.value = true; error.value = '';
  try {
    if (historical.value) {
      const capability = await requestApi({ url: `${url}options/`, noMockFallback: true });
      if (current !== generation) return;
      if (!capability.success || capability.data?.historical_exchange_supported !== true) throw new Error('当前后端尚未加载历史补录功能，请先重启本地后端；未发送导入请求。');
    }
    const data = new FormData(); data.append('file', file.value);
    if (props.kind === 'exchange') data.append('historical', String(historical.value));
    if (attachments.value) data.append('attachments', attachments.value);
    if (confirm) { data.append('file_hash', preview.value.file_hash); data.append('valid_only', String(validOnly.value)); }
    const response = await requestApi({ method: 'post', url: `${url}${confirm ? 'import-confirm' : 'import-preview'}/`, data, timeout: 120000, noMockFallback: true });
    if (current !== generation) return;
    if (!response.success) throw new Error(response.message);
    preview.value = response.data;
    if (confirm) emit('imported');
  } catch (e) {
    if (current === generation) { error.value = `${e.message || '校验失败。'}${confirm ? ' 导入结果可能尚未确认，请保留原文件重新校验；已生成记录会识别为已存在，不要直接重复创建。' : ' 请核对本页面模板、表头和附件后重试。'}`; if (confirm) preview.value = null; }
  } finally { if (current === generation) busy.value = false; }
}
async function downloadTemplate() {
  const current = generation;
  try { const result = await downloadApiFile(`${base()}template/`, `${title.value}-模板.xlsx`); if (result?.success === false) throw new Error(result.message); }
  catch (e) { if (current === generation) error.value = e.message; }
}
function downloadErrors() {
  const escape = value => `"${String(value ?? '').replaceAll('"', '""').replace(/^\s*[=+@-]/, "'$&")}"`;
  const content = '\ufeff' + [['Excel行号', '分组号', '原因'], ...preview.value.results.filter(row => !row.valid).map(row => [row.rows.join(', '), row.group, row.error])].map(row => row.map(escape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = '登记错误清单.csv'; a.click(); URL.revokeObjectURL(url);
}
watch(() => props.kind, reset);
watch(historical, () => { generation++; preview.value = null; validOnly.value = false; error.value = ''; });
watch(() => props.kind, () => { historical.value = false; });
onBeforeUnmount(() => { generation++; });
defineExpose({ busy, hasFiles: computed(() => Boolean(file.value || attachments.value)) });
</script>

<style scoped>
.registration-import { display: grid; gap: 16px; min-width: 0; }
.import-steps { display: flex; gap: 24px; margin: 0; padding: 0 0 14px 20px; border-bottom: 1px solid var(--el-border-color); color: #475569; font-size: 13px; flex-wrap: wrap; }
.import-steps .active { color: var(--el-color-primary); font-weight: 600; }
.import-heading, .import-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.import-heading { justify-content: space-between; }.import-heading > div { flex: 1 1 340px; }
h3 { margin: 0 0 6px; font-size: 15px; color: #20313d; } p, small, .import-actions span { margin: 0; color: #475569; font-size: 13px; line-height: 1.7; }
.import-files { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
label { display: grid; align-content: start; gap: 8px; padding: 14px; border: 1px solid var(--el-border-color); border-radius: 7px; color: #20313d; font-size: 13px; }
input { width: 100%; font: inherit; } input::file-selector-button { padding: 6px 10px; margin-right: 8px; border: 1px solid var(--el-border-color); border-radius: 5px; background: #fff; color: #334155; cursor: pointer; font: inherit; }
.import-actions :deep(.el-button + .el-button) { margin-left: 0; }.import-actions :deep(.el-checkbox) { height: auto; white-space: normal; }.import-actions :deep(.el-checkbox__label) { white-space: normal; }
.preview-summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; color: #334155; font-size: 13px; }
.boundary { padding-top: 12px; border-top: 1px solid var(--el-border-color); }.el-table b, .el-table small { display: block; }.limits { font-size: 12px; }
@media (max-width: 650px) { .import-files { grid-template-columns: 1fr; }.import-steps { gap: 12px 24px; } }
</style>
