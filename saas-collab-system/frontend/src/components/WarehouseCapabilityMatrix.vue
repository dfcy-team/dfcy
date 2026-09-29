<template>
  <el-alert title="仓库只读开关来自共享接入配置审批；本页检查不会刷新令牌或启用同步任务。" type="info" :closable="false" show-icon />
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-table v-loading="loading" :data="rows" border stripe empty-text="当前权限范围内没有仓库授权">
    <el-table-column label="仓库" min-width="180"><template #default="{ row }">{{ row.warehouse_name || row.warehouse_code }}</template></el-table-column>
    <el-table-column prop="external_warehouse_code" label="服务商仓库编码" min-width="150" />
    <el-table-column label="读取" width="120"><template #default="{ row }">{{ row.read_enabled ? '开启（配置审批）' : '关闭（配置审批）' }}</template></el-table-column>
    <el-table-column label="写入" width="90"><template #default>关闭</template></el-table-column>
    <el-table-column label="连接检查" width="130"><template #default="{ row }">{{ labels[row.validation_status] || '未检查' }}</template></el-table-column>
    <el-table-column prop="last_verified_at" label="最近检查（UTC）" min-width="170" />
    <el-table-column prop="oauth_expires_at" label="令牌到期（UTC）" min-width="170" />
    <el-table-column label="操作" min-width="230"><template #default="{ row }">
      <el-button :disabled="!canCheck || !row.read_enabled || row.status !== 'active' || !row.oauth_token_available || Boolean(checking)" :loading="checking === row.id" @click="check(row)">只读检查</el-button>
      <el-button @click="router.push({ path: '/integrations/configs', query: { config_id: row.integration_config_id } })">查看接入配置</el-button>
    </template></el-table-column>
  </el-table>
  <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load" />
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { fetchWarehouseAuthorizations, checkJifengWarehouse } from '../api/integrations';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const rows = ref([]);
const page = ref(1);
const total = ref(0);
const loading = ref(false);
const checking = ref(null);
const error = ref('');
const labels = { incomplete: '待补充', pending: '未检查当前令牌', verified: '检查通过', failed: '检查失败' };
const canCheck = computed(() => auth.hasPermission('integrations.run_live_readonly'));

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchWarehouseAuthorizations({ page: page.value, page_size: 20, ...(route.query.warehouse_id ? { warehouse_id: route.query.warehouse_id } : {}) });
    if (!response?.success) throw new Error(response?.message || '读取仓库授权失败');
    rows.value = response.data?.results || [];
    total.value = Number(response.data?.count || 0);
  } catch (reason) { rows.value = []; total.value = 0; error.value = reason?.message || '读取仓库授权失败'; }
  finally { loading.value = false; }
}
async function check(row) {
  if (!canCheck.value || !row.read_enabled || row.status !== 'active' || checking.value) return;
  try { await ElMessageBox.confirm('调用绑定仓库的一页库存只读接口（1 条）。不刷新令牌，不启用任务。是否继续？', '确认只读检查', { type: 'warning' }); } catch { return; }
  checking.value = row.id;
  try {
    const response = await checkJifengWarehouse(row.id);
    if (!response?.success) throw new Error(response?.message || '只读检查失败');
    ElMessage.success('仓库只读检查通过，任务启停状态未改变。');
  } catch (reason) { ElMessage.error(reason?.message || '只读检查失败'); }
  finally { checking.value = null; await load(); }
}
onMounted(load);
watch(() => route.query.warehouse_id, () => { page.value = 1; load(); });
defineExpose({ load });
</script>
