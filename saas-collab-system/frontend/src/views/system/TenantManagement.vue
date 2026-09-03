<template>
  <AppPage
    eyebrow="SYSTEM MANAGEMENT"
    title="租户管理"
    subtitle="查看平台租户边界，并进入指定租户维护角色、菜单、操作、字段和数据范围权限。"
    boundary-note="平台租户目录和跨租户角色配置仅对 internal superuser 开放；普通租户管理员始终只能操作自己的租户。"
    :capability="capability"
  >
    <section class="tenant-toolbar" aria-label="租户筛选">
      <el-input v-model="search" clearable placeholder="搜索租户名称或编码" @keyup.enter="load" />
      <el-select v-model="status" clearable placeholder="全部状态" @change="load">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </section>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <section v-else class="tenant-table" aria-label="平台租户列表">
      <el-table :data="tenants" border table-layout="fixed">
        <el-table-column v-if="showField('name')" prop="name" label="租户名称" min-width="220" show-overflow-tooltip />
        <el-table-column v-if="showField('code')" prop="code" label="租户编码" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="showField('status')" prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="权限配置" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openRoleConfiguration(row)">配置角色权限</el-button>
          </template>
        </el-table-column>
      </el-table>
      <footer class="tenant-pagination">
        <span>共 {{ total }} 个租户</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="load"
        />
      </footer>
    </section>
  </AppPage>
</template>

<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchTenants } from '../../api/systemAdmin';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const router = useRouter();
const auth = useAuthStore();
const tenants = ref([]);
const state = ref('loading');
const errorMessage = ref('');
const capability = ref(useMock ? 'mock' : 'pending');
const search = ref('');
const status = ref('');
const page = ref(1);
const pageSize = 20;
const total = ref(0);

const fieldPermissions = {
  name: 'field.system.tenants.name.view',
  code: 'field.system.tenants.code.view',
  status: 'field.system.tenants.status.view',
};

function showField(field) {
  return auth.hasFieldPermission(fieldPermissions[field]);
}

function unpack(response) {
  return response?.data?.results || response?.data?.items || [];
}

async function load() {
  state.value = 'loading';
  const response = await fetchTenants({
    search: search.value.trim(),
    status: status.value || undefined,
    page: page.value,
    page_size: pageSize,
  });
  if (!response?.success) {
    state.value = statusFromApiResponse(response, typeof navigator === 'undefined' || navigator.onLine);
    errorMessage.value = response?.message || '租户目录加载失败';
    capability.value = response?.http_status ? 'pending' : 'degraded';
    return;
  }
  tenants.value = unpack(response);
  total.value = Number.isFinite(response.data?.count) ? response.data.count : tenants.value.length;
  capability.value = response.data?.api_status || (useMock ? 'mock' : 'pending');
  state.value = tenants.value.length ? 'ready' : 'empty';
}

function openRoleConfiguration(tenant) {
  router.push({ path: '/system/roles', query: { tenant_id: String(tenant.id) } });
}

load();
</script>

<style scoped>
.tenant-toolbar { display: grid; grid-template-columns: minmax(240px, 1fr) 180px auto; gap: 10px; align-items: center; margin-bottom: 16px; padding: 12px; border: 1px solid #dbe3ec; background: #fff; }
.tenant-table { border: 1px solid #dbe3ec; background: #fff; }
.tenant-pagination { display: flex; align-items: center; justify-content: space-between; padding: 12px; color: #64748b; font-size: 13px; }
@media (max-width: 640px) { .tenant-toolbar { grid-template-columns: 1fr auto; } .tenant-toolbar .el-select { grid-column: 1 / -1; } }
</style>
