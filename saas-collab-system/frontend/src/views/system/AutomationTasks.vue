<template>
  <section v-loading="loading">
    <h2>自动化任务</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-tabs v-model="tab" @tab-change="reset">
      <el-tab-pane label="任务总览" name="overview" />
      <el-tab-pane label="任务列表" name="tasks" />
      <el-tab-pane label="运行记录" name="runs" />
    </el-tabs>
    <div v-if="tab === 'overview'" class="summary">
      <el-card v-for="(label, key) in labels" :key="key"><div>{{ label }}</div><strong>{{ overview[key] ?? '—' }}</strong></el-card>
    </div>
    <template v-else>
      <el-tag v-if="taskFilter" closable @close="clearTaskFilter">当前任务运行记录</el-tag>
      <el-form inline @submit.prevent="reset">
        <el-form-item label="搜索"><el-input v-model="search" clearable placeholder="任务名称" @clear="reset" /></el-form-item>
        <el-form-item label="来源"><el-select v-model="source" clearable style="width:160px" @change="reset"><el-option v-for="(label,key) in sources" :key="key" :label="label" :value="key" /></el-select></el-form-item>
        <el-button @click="reset">查询</el-button>
      </el-form>
      <el-table :data="rows" border empty-text="暂无记录">
        <el-table-column prop="name" label="任务" min-width="210"><template #default="{row}"><el-button v-if="tab !== 'runs' || row.task_id || row.sync_job_id" link type="primary" @click="openDetail(row)">{{ row.name || row.task_name || (row.sync_job_id ? '同步任务 #' + row.sync_job_id : row.task_id) }}</el-button><span v-else>{{ row.name || row.task_name || '临时批次' }}</span></template></el-table-column>
        <el-table-column label="来源" width="130"><template #default="{row}">{{ sources[row.source] || row.source || '—' }}</template></el-table-column>
        <el-table-column prop="module" label="模块" />
        <el-table-column v-if="tab === 'tasks'" label="启停"><template #default="{row}">{{ enabledText(row.enabled) }}</template></el-table-column>
        <el-table-column label="状态"><template #default="{row}">{{ states[row.state || row.status] || row.state || row.status || '未采集' }}</template></el-table-column>
        <el-table-column v-if="tab === 'tasks'" prop="schedule" label="排程" min-width="180" />
        <el-table-column label="下次触发 / 开始时间" min-width="185"><template #default="{row}">{{ format(row.next_run_at || row.started_at) }}</template></el-table-column>
        <el-table-column label="结果" min-width="180"><template #default="{row}">{{ resultText(row.last_result || row.result || row.error_code) }}</template></el-table-column>
        <el-table-column v-if="tab === 'runs'" label="结束时间" min-width="185"><template #default="{row}">{{ format(row.finished_at) }}</template></el-table-column>
        <el-table-column v-if="tab === 'runs'" label="耗时"><template #default="{row}">{{ duration(row) }}</template></el-table-column>
        <el-table-column v-if="tab === 'tasks'" label="观测时间" min-width="185"><template #default="{row}">{{ format(row.observed_at) }}<el-tag v-if="row.stale" type="warning">待确认</el-tag></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </template>
    <el-button @click="load">刷新</el-button>
    <el-drawer v-model="drawer" title="任务详情" size="560px">
      <div v-loading="detailLoading">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item v-for="(label,key) in detailLabels" :key="key" :label="label">{{ displayDetail(key) }}</el-descriptions-item>
        </el-descriptions>
        <el-button v-if="detail?.id" @click="showRuns">查看运行记录</el-button>
        <el-button v-if="detail?.business_url" link type="primary" @click="router.push(detail.business_url)">打开业务页面</el-button>
      </div>
    </el-drawer>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getAutomation } from '../../api/automation';
const router = useRouter();
const tab = ref('overview'), overview = ref({}), rows = ref([]), total = ref(0), page = ref(1);
const taskFilter = ref('');
const search = ref(''), source = ref(''), loading = ref(false), error = ref('');
const drawer = ref(false), detail = ref(null), detailLoading = ref(false), detailError = ref('');
const labels = { total:'任务总数', enabled:'启用', paused:'暂停', running:'运行中', failed:'失败', unknown:'未采集', stale:'待确认' };
const sources = { flash:'闪购计划', beat:'Celery Beat', sync_job:'业务同步', systemd:'服务器定时器', cron:'服务器 Cron' };
const states = { enabled:'启用', paused:'暂停', running:'运行中', success:'成功', completed:'完成', failed:'失败', unknown:'未采集', queued:'排队', partial:'部分完成', idle:'空闲', disabled:'停用', finished:'已结束', pending:'待完成', skipped:'已跳过', blocked:'受阻', cancelled:'已取消' };
const detailLabels = { name:'任务', source:'来源', module:'模块', schedule:'排程', timezone:'时区', enabled:'启停', state:'调度状态', next_run_at:'下次触发', observed_at:'观测时间', last_result:'最近结果' };
const format = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone:'Asia/Shanghai', hour12:false }) : '未采集';
const enabledText = value => value === true ? '启用' : value === false ? '停用' : '未采集';
const duration = row => row.started_at && row.finished_at ? Math.max(0, Math.round((new Date(row.finished_at) - new Date(row.started_at)) / 1000)) + ' 秒' : '—';
const resultText = value => value ? (typeof value === 'string' ? value : JSON.stringify(value)) : '暂无结果';
function displayDetail(key) {
  const value = detail.value[key];
  if (key.endsWith('_at')) return format(value);
  if (key === 'enabled') return enabledText(value);
  if (key === 'source') return sources[value] || value;
  if (key === 'state') return states[value] || value;
  if (key === 'last_result') return resultText(value);
  return value ?? '未采集';
}
let sequence = 0;
async function load() {
  const current = ++sequence;
  loading.value = true; error.value = '';
  try {
    const response = await getAutomation(tab.value === 'overview' ? 'tasks/overview/' : tab.value === 'runs' ? 'runs/' : 'tasks/', { search:search.value, source:source.value, page:page.value, page_size:20, task_id: tab.value === 'runs' ? taskFilter.value : undefined });
    if (current !== sequence) return;
    const data = response.data?.data ?? response.data;
    if (tab.value === 'overview') overview.value = data;
    else { rows.value = data.results || []; total.value = data.count || 0; }
  } catch (e) { if (current === sequence) error.value = e.response?.data?.message || '读取自动化任务失败，请重试。'; }
  finally { if (current === sequence) loading.value = false; }
}
function showRuns() { source.value = ''; search.value = ''; taskFilter.value = detail.value.id; drawer.value = false; tab.value = 'runs'; reset(); }
function clearTaskFilter() { taskFilter.value = ''; reset(); }
function reset() { page.value = 1; load(); }
let detailSequence = 0;
async function openDetail(row) {
  const current = ++detailSequence;
  drawer.value = true; detail.value = null; detailError.value = ''; detailLoading.value = true;
  try {
    const response = await getAutomation('tasks/' + encodeURIComponent(row.task_id || (row.sync_job_id ? 'sync:' + row.sync_job_id : row.id)) + '/');
    if (current === detailSequence) detail.value = response.data?.data ?? response.data;
  } catch { if (current === detailSequence) detailError.value = '读取任务详情失败。'; }
  finally { if (current === detailSequence) detailLoading.value = false; }
}
onMounted(load);
</script>
<style scoped>
.summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; margin-bottom:20px; }
.summary strong { font-size:28px; }
.el-pagination { margin:18px 0; }
</style>
