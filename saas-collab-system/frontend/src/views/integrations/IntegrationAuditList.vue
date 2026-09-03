<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="集成审计"
    subtitle="按接入配置、平台和 action 查询脱敏的授权、映射、能力与同步操作记录。"
    boundary-note="审计记录只读，敏感字段由后端脱敏后返回。页面不提供删除、修改、导出或凭据查看能力。"
    :capability="capability"
  >
    <template #action><el-button :loading="loading" @click="load">刷新</el-button></template>

    <section class="toolbar" aria-label="集成审计筛选">
      <el-input v-model="filters.config_id" clearable placeholder="配置 ID" @keyup.enter="applyFilters" />
      <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters">
        <el-option label="Lazada" value="lazada" />
        <el-option label="Shopee" value="shopee" />
        <el-option label="TikTok Shop" value="tiktok" />
      </el-select>
      <el-input v-model="filters.action" clearable placeholder="action（精确匹配）" @keyup.enter="applyFilters" />
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />
    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无集成审计记录">
      <el-table-column prop="id" label="事件 ID" width="90" />
      <el-table-column prop="created_at" label="时间" min-width="190" />
      <el-table-column prop="platform" label="平台" width="110" />
      <el-table-column prop="environment" label="环境" width="110" />
      <el-table-column prop="integration_config_id" label="配置 ID" width="95" />
      <el-table-column prop="action" label="action" min-width="210" />
      <el-table-column prop="actor_id" label="操作人" width="95" />
      <el-table-column prop="result" label="结果" width="110">
        <template #default="{ row }"><el-tag :type="resultType(row.result)" effect="plain">{{ resultLabel(row.result) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="脱敏详情" min-width="320" show-overflow-tooltip>
        <template #default="{ row }">{{ detailText(row.masked_detail) }}</template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="110">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="detailLoading" @click="openDetail(row)">查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination" aria-label="集成审计分页">
      <span class="pagination-total">共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next, jumper"
        @current-change="load"
        @size-change="handleSizeChange"
      />
    </div>

    <el-drawer v-model="detailOpen" title="集成审计详情" size="min(620px, 94vw)" destroy-on-close>
      <template v-if="selected.id">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="事件 ID">{{ selected.id }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ selected.created_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ selected.platform || '-' }}</el-descriptions-item>
          <el-descriptions-item label="环境">{{ selected.environment || '-' }}</el-descriptions-item>
          <el-descriptions-item label="配置 ID">{{ selected.integration_config_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="action">{{ selected.action || '-' }}</el-descriptions-item>
          <el-descriptions-item label="操作人">{{ selected.actor_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="结果">
            <el-tag :type="resultType(selected.result)" effect="plain">{{ resultLabel(selected.result) }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <section class="detail-section" aria-label="脱敏详情">
          <h3>脱敏详情</h3>
          <pre class="detail-json">{{ detailText(selected.masked_detail) }}</pre>
        </section>
      </template>
      <el-empty v-else description="请选择一条审计记录" />
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { useMock } from '../../api/request';
import { fetchIntegrationAudit } from '../../api/integrations';

const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const error = ref('');
const rows = ref([]);
const filters = reactive({ config_id: '', platform: '', action: '' });
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const detailOpen = ref(false);
const detailLoading = ref(false);
const selected = ref({});
function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function detailText(detail) {
  if (!detail) return '-';
  try { return JSON.stringify(detail); } catch { return '[已脱敏]'; }
}
function resultLabel(value) { return ({ success: '成功', failed: '失败', blocked: '已阻断', error: '失败' })[value] || value || '未知'; }
function resultType(value) { return ({ success: 'success', failed: 'danger', blocked: 'warning', error: 'danger' })[value] || 'info'; }
function openDetail(row) {
  if (detailLoading.value) return;
  selected.value = { ...row };
  detailOpen.value = true;
}
async function load() {
  loading.value = true;
  error.value = '';
  const response = await fetchIntegrationAudit({ ...filters, page: page.value, page_size: pageSize.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (response?.success) {
    rows.value = responseRows(response);
    const data = response?.data;
    total.value = Number(data?.count ?? data?.total ?? rows.value.length);
  } else {
    rows.value = [];
    total.value = 0;
    error.value = response?.message || '读取集成审计失败。';
  }
  loading.value = false;
}
function handleSizeChange(size) { pageSize.value = size; page.value = 1; load(); }
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { config_id: '', platform: '', action: '' }); applyFilters(); }
onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.toolbar .el-input { width: 190px; }
.toolbar .el-select { width: 155px; }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.pagination :deep(.el-pagination) { margin-left: auto; }
.page-alert { margin-bottom: 14px; }
.detail-section { margin-top: 20px; }
.detail-section h3 { margin: 0 0 8px; color: #172033; font-size: 15px; }
.detail-json { overflow: auto; max-height: 320px; margin: 0; padding: 12px; border: 1px solid #dbe3ec; border-radius: 6px; background: #f8fafc; color: #334155; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 760px) { .pagination { align-items: flex-start; flex-direction: column; } .pagination :deep(.el-pagination) { margin-left: 0; } }
</style>
