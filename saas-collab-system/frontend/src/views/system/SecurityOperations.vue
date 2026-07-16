<template>
  <AppPage
    eyebrow="SECURITY OPERATIONS"
    title="安全运维"
    subtitle="集中查看账号健康、凭据引用状态与最近操作审计。"
    boundary-note="本页面不返回或展示 credential_ciphertext、API Key、API Secret、Token、Cookie、Session 或密码明文。"
    :capability="capability"
  >
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <section class="security-summary">
        <div v-for="item in summaryItems" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
      </section>

      <section class="security-band">
        <header><div><h2>凭据引用</h2><p>仅显示别名、指纹、密钥版本和轮换时间</p></div><el-tag type="success" effect="plain">仅元数据</el-tag></header>
        <el-table :data="data.credential_references" border empty-text="暂无凭据引用">
          <el-table-column prop="platform" label="平台" min-width="120" />
          <el-table-column prop="account_alias" label="账号别名" min-width="180" />
          <el-table-column prop="environment" label="环境" min-width="110" />
          <el-table-column prop="credential_fingerprint" label="指纹" min-width="220" show-overflow-tooltip />
          <el-table-column prop="credential_key_version" label="密钥版本" min-width="130" />
          <el-table-column prop="last_verified_at" label="最近验证" min-width="170">
            <template #default="{ row }">{{ row.last_verified_at || '未验证' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="110" />
        </el-table>
      </section>

      <section class="security-band">
        <header><div><h2>最近审计</h2><p>用户、角色和基础档案操作均写入 tenant 审计记录</p></div></header>
        <el-table :data="data.recent_audit" border empty-text="暂无审计记录">
          <el-table-column prop="module" label="模块" min-width="120" />
          <el-table-column prop="action" label="动作" min-width="190" />
          <el-table-column prop="object_type" label="对象类型" min-width="130" />
          <el-table-column prop="object_id" label="对象ID" min-width="110" />
          <el-table-column prop="created_at" label="时间" min-width="190" />
        </el-table>
      </section>
    </template>
  </AppPage>
</template>

<script setup>
import { computed, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchSecurityOperations } from '../../api/systemAdmin';
import { useMock } from '../../api/request';
import { statusFromApiResponse } from '../../utils/uiState';

const state = ref('loading');
const capability = ref(useMock ? 'mock' : 'pending');
const errorMessage = ref('');
const data = ref({ summary: {}, credential_references: [], recent_audit: [] });
const summaryItems = computed(() => [
  { label: '启用账号', value: data.value.summary.active_users || 0 },
  { label: '停用账号', value: data.value.summary.inactive_users || 0 },
  { label: '启用角色', value: data.value.summary.active_roles || 0 },
  { label: '凭据引用', value: data.value.summary.credential_references || 0 }
]);

async function load() {
  state.value = 'loading';
  const response = await fetchSecurityOperations();
  if (!response.success) {
    state.value = statusFromApiResponse(response, navigator.onLine);
    errorMessage.value = response.message;
    capability.value = response.http_status ? 'pending' : 'degraded';
    return;
  }
  data.value = response.data;
  const apiStatus = response.data.api_status || response.data.status || (useMock ? 'mock' : 'pending');
  capability.value = apiStatus === 'fallback' ? 'degraded' : apiStatus;
  state.value = 'ready';
}
load();
</script>

<style scoped>
.security-summary { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.security-summary > div { min-height: 82px; padding: 15px 18px; border-right: 1px solid #e5eaf0; }
.security-summary > div:last-child { border-right: 0; }
.security-summary span, .security-summary strong { display: block; }
.security-summary span { color: #64748b; font-size: 12px; }
.security-summary strong { margin-top: 8px; color: #172033; font-size: 23px; }
.security-band { margin-top: 16px; }
.security-band header { display: flex; align-items: flex-start; justify-content: space-between; padding: 14px 16px; border: 1px solid #dbe3ec; border-bottom: 0; background: #fff; }
.security-band h2 { margin: 0; color: #172033; font-size: 16px; }
.security-band p { margin: 5px 0 0; color: #64748b; font-size: 12px; }
@media (max-width: 700px) { .security-summary { grid-template-columns: repeat(2, 1fr); } .security-summary > div:nth-child(2) { border-right: 0; } .security-summary > div:nth-child(-n + 2) { border-bottom: 1px solid #e5eaf0; } }
</style>
