<template>
  <section class="report-library">
    <header>
      <h1>报表中心</h1>
      <p>业务报表保留在对应模块；在这里选择数据集、保存个人视图或查看共享配置。</p>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-tabs v-model="tab">
      <el-tab-pane label="报表目录" name="catalog"
        ><div class="catalog">
          <article v-for="item in datasets" :key="item.id">
            <el-tag effect="plain">{{ item.module }}</el-tag>
            <h2>{{ item.name }}</h2>
            <p>{{ item.note }}</p>
            <el-button @click="openDataset(item.id)">自助分析</el-button>
          </article>
        </div></el-tab-pane
      >
      <el-tab-pane label="我的报表" name="mine"
        ><div class="catalog">
          <article v-for="view in views.filter((v) => v.is_owner)" :key="view.id">
            <h2>{{ view.name }}</h2>
            <p>{{ view.is_shared ? '已共享配置' : '个人视图' }} · {{ view.updated_at }}</p>
            <el-button @click="openView(view)">打开</el-button><el-button @click="remove(view.id)">删除视图</el-button>
          </article>
        </div>
        <el-empty v-if="!views.some((v) => v.is_owner)" description="在自助分析中保存配置后，会出现在这里。"
      /></el-tab-pane>
      <el-tab-pane label="共享报表" name="shared"
        ><p>共享配置会按当前查看者的业务权限重新读取数据。</p>
        <div class="catalog">
          <article v-for="view in views.filter((v) => v.is_shared)" :key="view.id">
            <h2>{{ view.name }}</h2>
            <el-button @click="openView(view)">打开</el-button>
          </article>
        </div></el-tab-pane
      >
      <el-tab-pane label="自助分析" name="analysis"
        ><ReportWorkbench v-if="tab === 'analysis'" :key="workbenchKey" :view-config="viewConfig" @saved="loadViews"
      /></el-tab-pane>
      <el-tab-pane label="待接入报表" name="pending"
        ><el-table :data="pending"
          ><el-table-column prop="name" label="报表" min-width="180" /><el-table-column
            prop="module"
            label="归属模块"
            min-width="180" /><el-table-column prop="reason" label="开放条件" min-width="350" /></el-table
      ></el-tab-pane>
    </el-tabs>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { fetchReportDatasets, fetchSavedReportViews, deleteReportView } from '../../api/reporting';
import ReportWorkbench from './ReportWorkbench.vue';
const tab = ref('catalog'),
  datasets = ref([]),
  pending = ref([]),
  views = ref([]),
  error = ref(''),
  viewConfig = ref(null),
  workbenchKey = ref(0);
async function loadViews() {
  const response = await fetchSavedReportViews();
  if (response.success) views.value = response.data || [];
  else error.value = response.message;
}
function openDataset(id) {
  const item = datasets.value.find((row) => row.id === id);
  viewConfig.value = { dataset: id, ...item.defaults, filters: {}, chart: 'table', pivot: '', ordering: '' };
  workbenchKey.value++;
  tab.value = 'analysis';
}
function openView(view) {
  viewConfig.value = view.config;
  workbenchKey.value++;
  tab.value = 'analysis';
}
async function remove(id) {
  const response = await deleteReportView(id);
  if (response.success) await loadViews();
  else error.value = response.message;
}
onMounted(async () => {
  try {
    const [response] = await Promise.all([fetchReportDatasets(), loadViews()]);
    if (!response.success) throw new Error(response.message);
    datasets.value = response.data.datasets || [];
    pending.value = response.data.pending || [];
  } catch (failure) {
    error.value = failure.message;
  }
});
</script>
<style scoped>
.report-library {
  display: grid;
  gap: 16px;
}
h1 {
  margin: 0;
  font-size: 24px;
}
.catalog {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.catalog article {
  padding: 18px;
  background: #fff;
  border: 1px solid #dce3ec;
  border-radius: 6px;
}
.catalog h2 {
  font-size: 16px;
}
.catalog p,
header p {
  font-size: 13px;
  color: #526177;
  line-height: 1.7;
}
.report-library {
  min-width: 0;
}
.report-library :deep(.el-tabs) {
  min-width: 0;
  width: 100%;
}
.catalog article {
  min-width: 0;
}
.catalog p,
header p {
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .catalog {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
