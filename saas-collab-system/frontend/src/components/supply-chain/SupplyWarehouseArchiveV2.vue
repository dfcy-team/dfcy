<template>
  <section class="warehouse-archive">
    <div class="toolbar">
      <el-input v-model="search" :disabled="saving" clearable placeholder="搜索系统编码、名称或飞书旧编码" @keyup.enter="load" @clear="load" />
      <el-select v-model="country" :disabled="saving" clearable placeholder="全部国家" @change="load">
        <el-option v-for="item in options.countries" :key="item.country_code" :label="`${item.name}（${item.country_code}）`" :value="item.country_code" />
      </el-select>
      <el-select v-model="status" :disabled="saving" clearable placeholder="全部状态" @change="load">
        <el-option label="启用" value="active" /><el-option label="停用" value="inactive" />
      </el-select>
      <el-button :disabled="saving" @click="load">查询</el-button>
      <el-button v-if="canCreate" type="primary" :disabled="saving" @click="openCreate">新增仓库</el-button>
    </div>
    <el-alert v-if="auth.authorizationStale" type="warning" :closable="false" title="权限状态已过期，请刷新授权后再维护仓库。" />
    <el-table v-loading="loading" :data="rows" row-key="id" stripe>
      <el-table-column prop="code" label="系统编码" min-width="130" />
      <el-table-column prop="legacy_codes" label="飞书旧编码" min-width="150"><template #default="{ row }">{{ row.legacy_codes?.join('、') || '—' }}</template></el-table-column>
      <el-table-column prop="name" label="仓库名称" min-width="150" />
      <el-table-column prop="country_code" label="国家" width="90" />
      <el-table-column prop="warehouse_type" label="仓库类型" width="120"><template #default="{row}">{{warehouseTypes.find(item=>item.value===row.warehouse_type)?.label || row.warehouse_type}}</template></el-table-column>
      <el-table-column prop="service_platform_name" label="仓储服务平台" min-width="150"><template #default="{row}">{{row.service_platform_name || '—'}}</template></el-table-column>
      <el-table-column label="第三方 WMS 身份" min-width="230">
        <template #default="{ row }">
          <div v-for="(mapping, index) in row.wms_mappings" :key="`${row.id}-${index}`" class="mapping">
            <strong>{{ mapping.provider }}</strong><span>仓库代码：{{ mapping.external_warehouse_code || '—' }}</span>
            <span>区域：{{ mapping.external_warehouse_region || '—' }}</span><el-tag size="small">{{mapping.status==='authorized'?'已授权':mapping.status==='active'?'启用':mapping.status}}</el-tag>
          </div>
          <span v-if="!row.wms_mappings?.length">未绑定</span>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="saving || auth.authorizationStale || !row.can_manage" @click="openEdit(row)">编辑业务资料</el-button></template></el-table-column>
    </el-table>
    <div class="pager"><el-pagination v-model:current-page="page" :disabled="saving" :page-size="20" :total="count" layout="total, prev, pager, next" @current-change="load" /></div>
    <el-dialog :model-value="dialogOpen" :title="editing ? '编辑仓库业务资料' : '新增仓库档案'" width="min(620px, 96vw)" top="4vh" class="sc2-scroll-dialog" append-to-body :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" destroy-on-close @update:model-value="updateDialogOpen">
      <el-form label-position="top">
        <template v-if="!editing">
          <el-form-item label="系统编码"><el-input v-model="form.code" :disabled="saving || auth.authorizationStale" maxlength="80" /></el-form-item>
          <el-form-item label="国家"><el-select v-model="form.country_code" :disabled="saving || auth.authorizationStale" filterable><el-option v-for="item in options.countries" :key="item.country_code" :label="`${item.name}（${item.country_code}）`" :value="item.country_code" /></el-select></el-form-item>
          <el-form-item label="仓库类型"><el-select v-model="form.warehouse_type" :disabled="saving || auth.authorizationStale" @change="clearServicePlatform"><el-option v-for="item in warehouseTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="仓储服务平台"><el-select v-model="form.service_platform_id" clearable :disabled="saving || auth.authorizationStale || form.warehouse_type === 'owned'"><el-option v-for="item in platformOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        </template>
        <el-form-item label="仓库名称"><el-input v-model="form.name" :disabled="saving || auth.authorizationStale" maxlength="120" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" :disabled="saving || auth.authorizationStale" maxlength="500" /></el-form-item>
        <el-form-item label="区域"><el-input v-model="form.region" :disabled="saving || auth.authorizationStale" maxlength="80" /></el-form-item>
        <el-form-item label="飞书旧编码（每行一项）"><el-input v-model="aliasText" :disabled="saving || auth.authorizationStale" type="textarea" :rows="3" placeholder="用于展示和搜索，不参与 WMS 身份匹配" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" :disabled="saving || auth.authorizationStale" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status" :disabled="saving || auth.authorizationStale"><el-option label="启用" value="active" /><el-option label="停用" value="inactive" /></el-select></el-form-item>
        <el-alert v-if="editing" type="info" :closable="false" title="系统编码、国家、仓库类型、仓储服务平台及 WMS 身份只读；身份调整请使用现有高级管理入口。" />
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialogOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving || auth.authorizationStale" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import '../../styles/supplyCollaboration.css';
import { useAuthStore } from '../../stores/auth';
import { createSupplyWarehouse, createSupplyWarehouseIdempotencyKey, fetchSupplyWarehouseOptions, fetchSupplyWarehouses, updateSupplyWarehouse } from '../../api/supplyWarehousesV2';

const auth = useAuthStore();
const rows = ref([]); const count = ref(0); const loading = ref(false); const saving = ref(false); const createAllowed = ref(false);
const search = ref(''); const country = ref(''); const status = ref(''); const page = ref(1);
const dialogOpen = ref(false); const editing = ref(false); const selected = ref(null); const aliasText = ref('');
const pendingWrite = ref(null);
const options = reactive({ countries: [], service_platforms: [] });
const form = reactive({ code: '', name: '', country_code: '', warehouse_type: 'owned', service_platform_id: null, address: '', region: '', legacy_codes: [], notes: '', status: 'active', expected_version: undefined });
const warehouseTypes = [{ label: '自营仓', value: 'owned' }, { label: '三方仓', value: 'third_party' }, { label: '平台仓', value: 'platform' }];
const expectedPlatformType = { owned: 'warehouse_owned', third_party: 'warehouse_third_party', platform: 'warehouse_platform' };
const platformOptions = computed(() => options.service_platforms.filter((item) => item.platform_type === expectedPlatformType[form.warehouse_type]));
const canCreate = computed(() => !auth.authorizationStale && createAllowed.value);
let listRequestToken = 0;

function errorText(error, fallback) {
  return error?.response?.data?.message || error?.message || fallback;
}

async function load() {
  const token = ++listRequestToken;
  loading.value = true;
  try {
    const response = await fetchSupplyWarehouses({ search: search.value, country_code: country.value, status: status.value, limit: 20, offset: (page.value - 1) * 20 });
    if (token !== listRequestToken) return;
    if (response?.success) { rows.value = response.data || []; count.value = response.count || 0; createAllowed.value = response.can_create === true; }
    else ElMessage.error(response?.message || '仓库档案加载失败');
  } catch (error) {
    if (token === listRequestToken) ElMessage.error(errorText(error, '仓库档案加载失败'));
  } finally { if (token === listRequestToken) loading.value = false; }
}
function resetForm() { Object.assign(form, { code: '', name: '', country_code: '', warehouse_type: 'owned', service_platform_id: null, address: '', region: '', legacy_codes: [], notes: '', status: 'active', expected_version: undefined }); aliasText.value = ''; }
function openCreate() { if (saving.value || auth.authorizationStale) return; editing.value = false; selected.value = null; resetForm(); dialogOpen.value = true; }
function openEdit(row) { if (saving.value || auth.authorizationStale || !row.can_manage) return; editing.value = true; selected.value = row; Object.assign(form, { ...row, expected_version: row.version }); aliasText.value = (row.legacy_codes || []).join('\n'); dialogOpen.value = true; }
function clearServicePlatform() { if (!saving.value) form.service_platform_id = null; }
function updateDialogOpen(open) { if (!saving.value || open) dialogOpen.value = open; }
async function save() {
  if (saving.value) return;
  if (auth.authorizationStale) { ElMessage.warning('权限状态已过期，请刷新授权后再试。'); return; }
  const aliases = aliasText.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  const common = { name: form.name, address: form.address, region: form.region, legacy_codes: aliases, notes: form.notes, status: form.status };
  const payload = editing.value ? { ...common, expected_version: form.expected_version } : { ...common, code: form.code, country_code: form.country_code, warehouse_type: form.warehouse_type, service_platform_id: form.service_platform_id || null };
  const kind = editing.value ? 'update' : 'create';
  const id = editing.value ? selected.value.id : null;
  const signature = JSON.stringify({ kind, id, payload });
  if (pendingWrite.value?.signature !== signature) pendingWrite.value = { signature, key: createSupplyWarehouseIdempotencyKey() };
  const idempotencyKey = pendingWrite.value.key;
  saving.value = true;
  try {
    const response = editing.value
      ? await updateSupplyWarehouse(id, payload, idempotencyKey)
      : await createSupplyWarehouse(payload, idempotencyKey);
    if (!response?.success) { ElMessage.error(response?.message || '仓库档案保存失败'); return; }
    pendingWrite.value = null;
    ElMessage.success('仓库档案已保存'); dialogOpen.value = false; await load();
  } catch (error) {
    ElMessage.error(errorText(error, '仓库档案保存失败，请重试'));
  } finally { saving.value = false; }
}
async function initialize() {
  try {
    const response = await fetchSupplyWarehouseOptions();
    if (response?.success && response.data) Object.assign(options, response.data);
    else ElMessage.error(response?.message || '仓库选项加载失败');
  } catch (error) {
    ElMessage.error(errorText(error, '仓库选项加载失败'));
  }
  await load();
}
onMounted(() => { void initialize(); });
</script>

<style scoped>
.warehouse-archive{display:grid;gap:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.toolbar .el-input{width:min(360px,100%)}.toolbar .el-select{width:180px}.mapping{display:grid;grid-template-columns:1fr auto;gap:2px 8px;align-items:center}.mapping strong{grid-column:1/-1}.pager{display:flex;justify-content:flex-end;overflow:auto}
</style>
