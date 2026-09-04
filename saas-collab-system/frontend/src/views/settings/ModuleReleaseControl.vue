<template>
  <section class="module-release-page" :aria-busy="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">系统治理 · 模块发布</p>
        <h1>模块发布控制</h1>
        <p>统一控制各业务模块是否在当前环境显示和运行；状态通过配置版本审批后生效。</p>
      </div>
      <div class="header-actions">
        <el-tag type="warning">管理员可调整</el-tag>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-alert title="关闭模块会同时隐藏菜单、拦截直接路由访问，并拒绝对应后台任务。仅 Mock 只适用于本地开发，不会连接外部平台。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <section class="panel">
      <header class="panel-header"><div><h2>业务模块状态</h2><p>API 平台同步和全球刊登写入仍有独立的安全门与能力矩阵。</p></div></header>
      <div class="module-grid">
        <div v-for="module in moduleKeys" :key="module" class="module-row">
          <div><strong>{{ moduleLabels[module] }}</strong><small>{{ module }}</small></div>
          <el-select v-model="form.modules[module]" size="small" style="width: 150px">
            <el-option label="关闭" value="disabled" />
            <el-option label="仅 Mock" value="mock_only" />
            <el-option label="试运行只读" value="pilot_readonly" />
            <el-option label="正式启用" value="enabled" />
          </el-select>
        </div>
      </div>
      <div class="submit-bar">
        <el-input v-model="changeReason" maxlength="240" placeholder="填写本次变更原因（至少 5 个字符）" />
        <el-button type="primary" :loading="saving" :disabled="!manageAccess.allowed" @click="submit">提交待审批版本</el-button>
      </div>
      <small v-if="!manageAccess.allowed" class="hint">{{ manageAccess.reason }}</small>
    </section>

    <section class="panel">
      <header class="panel-header"><div><h2>配置版本</h2><p>审批人与创建人应分离；紧急下线可通过关闭版本并审批完成。</p></div></header>
      <el-table :data="versions" size="small" empty-text="暂无配置版本">
        <el-table-column prop="version" label="版本" width="90" />
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column prop="created_at" label="创建时间" min-width="170" />
        <el-table-column label="操作" width="280">
          <template #default="scope">
            <el-button v-if="scope.row.status === 'pending_approval'" size="small" type="success" :disabled="!approvalAccess.allowed || isOwnVersion(scope.row)" :title="isOwnVersion(scope.row) ? '创建人不能审批自己的版本' : approvalAccess.reason" @click="approve(scope.row)">审批生效</el-button>
            <el-button v-if="scope.row.status === 'effective'" size="small" :disabled="!rollbackAccess.allowed" :title="rollbackAccess.reason" @click="rollback(scope.row)">创建回滚版本</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  approveProductionIntegrationSettingsVersion,
  createProductionIntegrationSettingsVersion,
  fetchProductionIntegrationSettings,
  rollbackProductionIntegrationSettingsVersion
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const moduleKeys = ['core', 'masterdata', 'product_development', 'supply_chain', 'inventory', 'global_listing', 'sales', 'influencer', 'finance', 'analytics', 'decision', 'reports', 'workflow', 'rpa', 'api_integrations', 'system', 'governance'];
const moduleLabels = { core: '认证与租户', masterdata: '基础档案', product_development: '产品开发', supply_chain: '供应链协同', inventory: '库存管理', global_listing: '全球刊登', sales: '销售管理', influencer: '达人管理', finance: '财务中心', analytics: '经营分析', decision: '经营决策', reports: '报表中心', workflow: '流程协同', rpa: 'RPA 协同', api_integrations: 'API 数据接入', system: '系统管理', governance: '治理与试点' };
const form = reactive({ modules: Object.fromEntries(moduleKeys.map((key) => [key, 'enabled'])) });
const versions = ref([]);
const currentConfig = ref({ modules: { ...form.modules } });
const changeReason = ref('调整业务模块生产发布状态');
const loading = ref(false);
const saving = ref(false);
const error = ref('');

const access = (permission) => {
  const missing = [permission, 'config.system.manage'].filter((code) => !auth.hasPermission(code));
  return { allowed: missing.length === 0, reason: missing.length ? `缺少操作权限：${missing.join('、')}` : '' };
};
const manageAccess = access('config.manage');
const approvalAccess = access('config.approve');
const rollbackAccess = access('config.rollback');

function hydrate(data = {}) {
  const config = data.effective_config || data.config || data.runtime?.config || {};
  const modules = config.modules || {};
  const next = Object.fromEntries(moduleKeys.map((key) => [key, modules[key] || 'enabled']));
  Object.assign(form.modules, next);
  currentConfig.value = { modules: { ...next } };
  versions.value = Array.isArray(data.versions) ? data.versions : [];
}

function isOwnVersion(version) {
  return String(version.created_by?.id || version.created_by_id || '') === String(auth.currentUser?.id || auth.currentUser?.user_id || '');
}

async function load() {
  loading.value = true; error.value = '';
  if (!auth.hasPermission('config.view') || !auth.hasPermission('config.system.manage')) {
    error.value = '缺少查看模块发布状态的权限。'; loading.value = false; return;
  }
  try {
    const response = await fetchProductionIntegrationSettings();
    if (!response?.success) throw new Error(response?.message || '读取模块发布状态失败。');
    hydrate(response.data || {});
  } catch (loadError) { error.value = loadError.message || '读取模块发布状态失败。'; } finally { loading.value = false; }
}

async function submit() {
  if (!manageAccess.allowed) return;
  if (String(changeReason.value || '').trim().length < 5) { ElMessage.warning('变更原因至少需要 5 个字符。'); return; }
  const enabling = moduleKeys.some((key) => form.modules[key] === 'enabled' && currentConfig.value.modules[key] !== 'enabled');
  if (enabling) await ElMessageBox.confirm('本次变更会正式启用模块，请确认已完成该模块的生产验收。', '确认启用模块', { type: 'warning' });
  saving.value = true;
  try {
    const response = await createProductionIntegrationSettingsVersion({ value: { modules: { ...form.modules } }, change_reason: changeReason.value.trim() });
    if (!response?.success) throw new Error(response?.message || '提交失败。');
    ElMessage.success('模块配置已提交，等待审批。');
    await load();
  } catch (submitError) { if (submitError !== 'cancel') ElMessage.error(submitError.message || '提交失败。'); } finally { saving.value = false; }
}

async function approve(version) {
  if (!approvalAccess.allowed || isOwnVersion(version)) return;
  try {
    await ElMessageBox.confirm(`确认审批模块配置 v${version.version}？`, '审批确认', { type: 'warning' });
    const response = await approveProductionIntegrationSettingsVersion(version.id);
    if (!response?.success) throw new Error(response?.message || '审批失败。');
    ElMessage.success('模块配置已审批生效。'); await load();
  } catch (approveError) { if (approveError !== 'cancel') ElMessage.error(approveError.message || '审批失败。'); }
}

async function rollback(version) {
  if (!rollbackAccess.allowed) return;
  try {
    await ElMessageBox.confirm(`确认创建回滚到 v${version.version} 的待审批版本？`, '回滚确认', { type: 'warning' });
    const response = await rollbackProductionIntegrationSettingsVersion(version.id);
    if (!response?.success) throw new Error(response?.message || '回滚失败。');
    ElMessage.success('回滚版本已创建，等待审批。'); await load();
  } catch (rollbackError) { if (rollbackError !== 'cancel') ElMessage.error(rollbackError.message || '回滚失败。'); }
}

onMounted(load);
</script>

<style scoped>
.module-release-page { display: grid; gap: 16px; color: #14213a; }
.page-header, .panel-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.page-header h1 { margin: 4px 0 8px; font-size: 28px; }.page-header p { margin: 0; color: #60708b; }
.eyebrow { color: #5271ff !important; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
.header-actions { display: flex; gap: 10px; align-items: center; }.panel { background: #fff; border: 1px solid #e5ebf2; border-radius: 10px; overflow: hidden; }.panel-header { padding: 18px 20px; border-bottom: 1px solid #e5ebf2; }.panel-header h2 { margin: 0 0 4px; font-size: 18px; }.panel-header p { margin: 0; color: #71809a; font-size: 13px; }
.module-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 16px 20px; }.module-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px; border: 1px solid #e5ebf2; border-radius: 8px; background: #f9fbfd; }.module-row strong { display: block; }.module-row small { display: block; color: #8a96a8; margin-top: 3px; }.submit-bar { display: flex; gap: 10px; padding: 0 20px 18px; }.submit-bar .el-input { max-width: 520px; }.hint { display: block; padding: 0 20px 18px; color: #c26b00; }
@media (max-width: 760px) { .page-header, .panel-header { flex-direction: column; }.module-grid { grid-template-columns: 1fr; }.submit-bar { flex-direction: column; }.submit-bar .el-input { max-width: none; } }
</style>
