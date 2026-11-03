<template>
  <section class="import-history" aria-label="导入批次记录">
    <div class="history-heading"><p>仅展示本人确认的批次，登记结果按当前权限过滤。失败项请重新选择原文件校验；成功记录不会重复创建。</p><el-button :loading="busy" @click="load">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table v-loading="busy" :data="rows" empty-text="暂无导入记录。先校验模板，再确认导入草稿。" @row-click="selected = $event">
      <el-table-column label="批次／文件" min-width="220"><template #default="{ row }"><b>#{{ row.id }} · {{ row.file_name || '历史批次（未记录文件名）' }}</b><small>{{ row.attachment_name || '无附件文件名' }}</small></template></el-table-column>
      <el-table-column prop="imported_by" label="操作人" width="110" />
      <el-table-column label="导入时间" min-width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="可见结果" min-width="190"><template #default="{ row }">{{ row.results.filter(item => item.status === 'created').length }} 新建 / {{ row.results.filter(item => item.status === 'existing').length }} 已存在 / {{ row.results.filter(item => !item.valid).length }} 失败</template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click.stop="selected = row">详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-if="count" v-model:current-page="page" :total="count" :page-size="20" layout="total, prev, pager, next" @current-change="load" />
    <template v-if="selected"><div class="history-heading"><h3>批次 #{{ selected.id }} 的登记结果</h3><el-button v-if="canView" type="primary" plain @click="emit('view-batch', selected.id)">查看本批次登记</el-button></div>
      <el-table :data="selected.results" max-height="320" empty-text="当前权限下没有可见的登记结果">
        <el-table-column label="当前记录" min-width="130"><template #default="{ row }">{{ row.deleted ? '已删除，可查看详情恢复' : row.id ? '记录保留' : '未生成登记' }}</template></el-table-column>
        <el-table-column label="Excel行号" width="100"><template #default="{ row }">{{ row.rows.join(', ') }}</template></el-table-column><el-table-column prop="group" label="分组" min-width="100" /><el-table-column prop="store_code" label="店铺" min-width="110" /><el-table-column prop="order_number" label="订单号" min-width="160" /><el-table-column label="结果" min-width="120"><template #default="{ row }">{{ labels[row.status] || row.status }}</template></el-table-column><el-table-column prop="error" label="错误原因" min-width="230" /><el-table-column label="登记" width="90"><template #default="{ row }"><el-button v-if="row.id && canView" link type="primary" @click="emit('open-record', row.id)">#{{ row.id }}</el-button></template></el-table-column>
      </el-table>
      <div v-if="selected.results.some(row => !row.valid)"><el-button @click="downloadErrors">下载错误清单</el-button><el-button class="retry" @click="emit('retry')">重新选择原文件并校验失败项</el-button></div>
    </template>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { requestApi } from '../api/request';
const props = defineProps({ kind: { type: String, required: true }, canView: Boolean });
const emit = defineEmits(['open-record', 'view-batch', 'retry']);
const rows = ref([]), count = ref(0), page = ref(1), selected = ref(null), busy = ref(false), error = ref('');
const labels = { created: '已创建草稿', existing: '已存在', error: '未导入' };
let sequence = 0;
const formatTime = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
function downloadErrors() {
  const escape = value => `"${String(value ?? '').replaceAll('"', '""').replace(/^\s*[=+@-]/, "'$&")}"`;
  const content = '\ufeff' + [['Excel行号', '分组号', '原因'], ...selected.value.results.filter(row => !row.valid).map(row => [row.rows.join(', '), row.group, row.error])].map(row => row.map(escape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `导入批次-${selected.value.id}-错误清单.csv`; anchor.click(); URL.revokeObjectURL(url);
}
async function load() {
  const current = ++sequence;
  busy.value = true; error.value = ''; selected.value = null;
  try {
    const result = await requestApi({ url: `/api/internal/commerce/registrations/${props.kind}/imports/`, params: { page: page.value }, noMockFallback: true });
    if (current !== sequence) return;
    if (!result.success) throw new Error(result.message);
    rows.value = result.data.results; count.value = result.data.count;
  } catch (e) { if (current === sequence) { rows.value = []; count.value = 0; error.value = e.message || '导入记录读取失败，请重试。'; } }
  finally { if (current === sequence) busy.value = false; }
}
watch(() => props.kind, () => { page.value = 1; load(); });
onMounted(load);
onBeforeUnmount(() => { sequence++; });
</script>

<style scoped>
.import-history { display: grid; gap: 14px; min-width: 0; }.history-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; } p { flex: 1 1 300px; margin: 0; color: #475569; font-size: 13px; line-height: 1.7; } h3 { margin: 0; font-size: 15px; color: #20313d; }.el-table b, .el-table small { display: block; } small { margin-top: 4px; color: #475569; }.el-pagination { justify-content: flex-end; }.retry { justify-self: start; }
</style>
