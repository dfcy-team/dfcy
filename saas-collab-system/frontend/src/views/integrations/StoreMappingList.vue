<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="店铺映射"
    subtitle="将已授权的平台店铺绑定到当前租户店铺档案，并维护时区与结算币种。"
    boundary-note="当前店铺映射能力仅支持 Shopee、TikTok Shop；Lazada 已支持授权但映射尚未开放。映射写入只接受店铺与授权 ID，由后端校验租户、平台和数据范围；平台身份字段不可由页面伪造，映射不可删除，只能停用。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button v-if="canManage" type="primary" @click="openCreate">新建店铺映射</el-button>
    </template>

    <section class="toolbar" aria-label="店铺映射筛选">
      <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters">
        <el-option label="Shopee" value="shopee" />
        <el-option label="TikTok Shop" value="tiktok" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <el-input v-model="filters.store_id" clearable placeholder="店铺 ID" @keyup.enter="applyFilters" />
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />

    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无店铺映射，请先完成店铺授权">
      <el-table-column prop="id" label="映射 ID" width="90" />
      <el-table-column prop="platform" label="平台" width="120" />
      <el-table-column label="店铺档案" min-width="200">
        <template #default="{ row }">
          <div>{{ row.store_name || row.store_code || `店铺 #${row.store_id || '-'}` }}</div>
          <small>{{ row.store_code || `store_id=${row.store_id || '-'}` }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="authorization_id" label="授权 ID" width="100" />
      <el-table-column prop="platform_store_id" label="平台店铺 ID" min-width="190" show-overflow-tooltip />
      <el-table-column prop="region" label="区域" width="90" />
      <el-table-column prop="timezone" label="时区" min-width="165" />
      <el-table-column prop="currency" label="币种" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="mapping_source" label="来源" width="145" />
      <el-table-column label="操作" fixed="right" width="130">
        <template #default="{ row }"><el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑</el-button></template>
      </el-table-column>
    </el-table>

    <div class="pagination" aria-label="店铺映射分页">
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

    <el-dialog v-model="formOpen" :title="editingRow ? '编辑店铺映射' : '新建店铺映射'" width="min(620px, 94vw)" destroy-on-close>
      <el-alert
        title="创建只需填写租户内店铺 ID、有效授权 ID 和本地化字段；平台店铺 ID、平台身份和区域由授权关系决定。"
        type="info"
        show-icon
        :closable="false"
      />
      <el-form label-position="top" class="mapping-form">
        <template v-if="!editingRow">
          <el-form-item label="店铺档案 ID" required><el-input v-model="form.store_id" inputmode="numeric" placeholder="例如 1" /></el-form-item>
          <el-form-item label="店铺授权 ID" required><el-input v-model="form.authorization_id" inputmode="numeric" placeholder="例如 201" /></el-form-item>
        </template>
        <el-form-item v-else label="映射 ID"><el-input :model-value="String(editingRow.id)" disabled /></el-form-item>
        <el-form-item v-if="editingRow" label="状态">
          <el-select v-model="form.status" style="width: 100%"><el-option label="启用" value="active" /><el-option label="停用" value="inactive" /></el-select>
        </el-form-item>
        <el-form-item label="时区"><el-input v-model="form.timezone" placeholder="例如 Asia/Singapore" /></el-form-item>
        <el-form-item label="结算币种"><el-input v-model="form.currency" maxlength="3" placeholder="ISO 4217，例如 SGD" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">{{ editingRow ? '确认保存' : '确认创建' }}</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { createStoreMapping, fetchStoreMappings, updateStoreMapping } from '../../api/integrations';

const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const rows = ref([]);
const filters = reactive({ platform: '', status: '', store_id: '' });
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const form = reactive({ store_id: '', authorization_id: '', status: 'active', timezone: '', currency: '' });
const formOpen = ref(false);
const editingRow = ref(null);
const canManage = computed(() => auth.hasPermission('integrations.store.authorize'));

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
async function load() {
  loading.value = true;
  error.value = '';
  const response = await fetchStoreMappings({ ...filters, page: page.value, page_size: pageSize.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (response?.success) {
    rows.value = responseRows(response);
    const data = response?.data;
    total.value = Number(data?.count ?? data?.total ?? rows.value.length);
  } else {
    rows.value = [];
    total.value = 0;
    error.value = response?.message || '读取店铺映射失败。';
  }
  loading.value = false;
}
function handleSizeChange(size) { pageSize.value = size; page.value = 1; load(); }
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { platform: '', status: '', store_id: '' }); applyFilters(); }
function openCreate() {
  if (!canManage.value) return ElMessage.error('当前角色没有维护店铺映射的权限。');
  editingRow.value = null;
  Object.assign(form, { store_id: '', authorization_id: '', status: 'active', timezone: '', currency: '' });
  formOpen.value = true;
}
function openEdit(row) {
  if (!canManage.value) return ElMessage.error('当前角色没有维护店铺映射的权限。');
  editingRow.value = row;
  Object.assign(form, { store_id: row.store_id || '', authorization_id: row.authorization_id || '', status: row.status || 'active', timezone: row.timezone || '', currency: row.currency || '' });
  formOpen.value = true;
}
async function submitForm() {
  if (!canManage.value) return;
  let payload;
  if (editingRow.value) {
    payload = { status: form.status, timezone: String(form.timezone || '').trim(), currency: String(form.currency || '').trim().toUpperCase() };
  } else {
    const storeId = Number(form.store_id);
    const authorizationId = Number(form.authorization_id);
    if (!Number.isInteger(storeId) || storeId < 1 || !Number.isInteger(authorizationId) || authorizationId < 1) return ElMessage.warning('请填写有效的店铺 ID 和授权 ID。');
    payload = { store_id: storeId, authorization_id: authorizationId, timezone: String(form.timezone || '').trim(), currency: String(form.currency || '').trim().toUpperCase() };
  }
  try { await ElMessageBox.confirm(`${editingRow.value ? '确认保存店铺映射变更' : '确认创建店铺映射'}？操作将写入集成审计。`, '确认映射操作', { type: 'warning', confirmButtonText: '确认' }); } catch { return; }
  saving.value = true;
  const response = editingRow.value ? await updateStoreMapping(editingRow.value.id, payload) : await createStoreMapping(payload);
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '店铺映射保存失败。');
  ElMessage.success(editingRow.value ? '店铺映射已更新。' : '店铺映射已创建。');
  formOpen.value = false;
  await load();
}
onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.toolbar .el-select { width: 150px; }
.toolbar .el-input { width: 150px; }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.pagination :deep(.el-pagination) { margin-left: auto; }
.page-alert { margin-bottom: 14px; }
.mapping-form { margin-top: 18px; }
small { color: #64748b; }
@media (max-width: 760px) { .pagination { align-items: flex-start; flex-direction: column; } .pagination :deep(.el-pagination) { margin-left: 0; } }
</style>
