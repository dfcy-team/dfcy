<template>
  <main class="config-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">API 数据接入</p>
        <h1>连接配置</h1>
        <p>集中管理 Shopee 与 TikTok Shop 应用参数。密钥仅写入托管服务，本页不会显示原文。</p>
      </div>
      <el-button v-if="canCreate" type="primary" @click="router.push('/integrations/configs/new')">新建连接</el-button>
    </header>

    <el-alert
      title="真实网络与生产同步默认关闭；创建配置不等于平台已连接。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="table-card">
      <div class="filters">
        <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="load">
          <el-option label="Shopee" value="shopee" />
          <el-option label="TikTok Shop" value="tiktok" />
        </el-select>
        <el-select v-model="filters.environment" clearable placeholder="全部环境" @change="load">
          <el-option label="Mock" value="mock" />
          <el-option label="Sandbox" value="sandbox" />
          <el-option label="Pilot" value="pilot" />
          <el-option label="Production" value="production" />
        </el-select>
        <el-select v-model="filters.region" clearable placeholder="全部地区" @change="load">
          <el-option label="菲律宾（PH）" value="PH" />
          <el-option label="泰国（TH）" value="TH" />
          <el-option label="马来西亚（MY）" value="MY" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="全部状态" @change="load">
          <el-option label="草稿" value="draft" />
          <el-option label="已配置" value="configured" />
          <el-option label="已验证" value="verified" />
          <el-option label="错误" value="error" />
          <el-option label="已禁用" value="disabled" />
        </el-select>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="暂无连接配置" @row-click="openRow">
        <el-table-column label="平台 / 应用" min-width="220">
          <template #default="{ row }">
            <strong>{{ platformName(row.platform) }}</strong>
            <div class="muted">{{ row.account_alias }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="120" />
        <el-table-column label="地区" min-width="150">
          <template #default="{ row }">{{ (row.regions || []).join(' / ') || '-' }}</template>
        </el-table-column>
        <el-table-column label="凭据" width="140">
          <template #default="{ row }">
            <el-tag :type="row.credential_status === 'configured' ? 'success' : 'info'">
              {{ row.credential_status === 'configured' ? '******** 已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭据版本" width="110">
          <template #default="{ row }">v{{ row.credential_reference_version || 1 }}</template>
        </el-table-column>
        <el-table-column label="连接状态" width="130">
          <template #default="{ row }"><el-tag type="warning">{{ row.status || 'draft' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最后验证" min-width="180">
          <template #default="{ row }">{{ row.last_verified_at || '尚未验证' }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }"><el-button text type="primary" @click.stop="openRow(row)">配置</el-button></template>
        </el-table-column>
      </el-table>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { fetchIntegrationConfigs } from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';

const router = useRouter();
const auth = useAuthStore();
const loading = ref(false);
const rows = ref([]);
const filters = reactive({ platform: '', environment: '', region: '', status: '' });
const canCreate = computed(() => auth.hasPermission('integrations.config.create'));

function platformName(value) { return value === 'tiktok' ? 'TikTok Shop' : value === 'shopee' ? 'Shopee' : value; }
function openRow(row) { router.push(`/integrations/configs/${row.id}`); }
function responseRows(response) {
  if (Array.isArray(response?.data)) return response.data;
  return response?.data?.items || response?.data?.results || [];
}
async function load() {
  loading.value = true;
  const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
  const response = await fetchIntegrationConfigs(params);
  rows.value = response.success ? responseRows(response) : [];
  loading.value = false;
}
onMounted(load);
</script>

<style scoped>
.config-page { display: grid; gap: 20px; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; }
.page-heading h1 { margin: 4px 0 8px; font-size: 28px; letter-spacing: -.02em; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.table-card { padding: 18px; border: 1px solid var(--el-border-color-light); border-radius: 10px; background: var(--el-bg-color); }
.filters { display: flex; gap: 10px; margin-bottom: 16px; }
.filters .el-select { width: 180px; }
.muted { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; }
:deep(.el-table__row) { cursor: pointer; }
@media (max-width: 760px) { .page-heading { flex-direction: column; } .filters { flex-wrap: wrap; } }
</style>
