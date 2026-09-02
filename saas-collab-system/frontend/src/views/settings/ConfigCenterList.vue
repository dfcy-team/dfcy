<template>
  <Phase3DecisionPage
    ref="pageRef"
    eyebrow="系统治理"
    title="配置中心"
    subtitle="维护租户配置版本、审批状态与生效时间。"
    boundary-note="配置中心不提供真实平台密钥、银行密码、Cookie、Session 或明文 Token 输入；敏感项仅允许占位引用并由后端再次校验。"
    :loader="loadConfigCenter"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="配置项"
    table-note="配置写入、审批和生效均由后端按 tenant、permission、data_scope 与审计规则校验"
  >
    <template #action>
      <el-button
        v-if="createAccess.visible"
        type="primary"
        :disabled="createAccess.disabled || apiStatus !== 'connected'"
        :title="apiStatus !== 'connected' ? '等待真实配置接口联调完成' : createAccess.reason"
        @click="openCreate"
      >新建配置版本</el-button>
    </template>
  </Phase3DecisionPage>

  <el-dialog v-model="createOpen" title="新建配置版本" width="min(560px, 94vw)" destroy-on-close>
    <el-alert
      title="提交后将创建不可变版本；需要审批的配置会进入待审批状态。请勿输入任何密钥、Token、Cookie、Session 或密码。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-form label-position="top" class="config-form">
      <el-form-item label="配置项" required>
        <el-select v-model="newConfig.config_key" filterable style="width: 100%" placeholder="选择配置项">
          <el-option
            v-for="item in definitions"
            :key="item.config_key"
            :label="`${item.config_key}（${item.scope_type || item.scope || 'tenant'}）`"
            :value="item.config_key"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="配置值" required>
        <el-input
          v-model="newConfig.value"
          type="textarea"
          :rows="4"
          :placeholder="valuePlaceholder"
          autocomplete="off"
        />
      </el-form-item>
      <el-form-item label="生效时间" required>
        <el-date-picker
          v-model="newConfig.effective_at"
          type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ssZ"
          style="width: 100%"
          placeholder="选择生效时间"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createOpen = false">取消</el-button>
      <el-button type="primary" :loading="creating" @click="submitCreate">创建版本</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import {
  approveConfigValue,
  createConfigValue,
  fetchConfigDefinitions,
  fetchConfigValues
} from '../../api/configCenter';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const pageRef = ref(null);
const definitions = ref([]);
const apiStatus = ref(useMock ? 'mock' : 'pending');
const createOpen = ref(false);
const creating = ref(false);
const newConfig = reactive({ config_key: '', value: '', effective_at: new Date().toISOString() });
const createAccess = computed(() => getActionAccess(auth, { permission: 'config.manage' }));

const filters = [
  { key: 'scope', label: '范围', options: [{ label: '租户级', value: 'tenant' }, { label: '系统级', value: 'system' }] },
  {
    key: 'status',
    label: '状态',
    options: [
      { label: '待审批', value: 'pending_approval' },
      { label: '已批准', value: 'approved' },
      { label: '生效中', value: 'effective' },
      { label: '已替代', value: 'superseded' }
    ]
  }
];
const columns = [
  { prop: 'config_key', label: '配置键', width: 220 },
  { prop: 'scope_type', label: '范围' },
  { prop: 'value_type', label: '值类型' },
  { prop: 'version', label: '当前版本' },
  { prop: 'value_summary', label: '当前值摘要', width: 180 },
  { prop: 'latest_status', label: '状态', type: 'status' },
  { prop: 'requires_approval', label: '需要审批', type: 'status' },
  { prop: 'effective_at', label: '生效时间', width: 180 }
];
const rowActions = [
  { label: '治理信息', mode: 'detail' },
  {
    label: '审批',
    permission: 'config.approve',
    type: 'success',
    when: (row) => row.latest_status === 'pending_approval' && row.latest_version_id,
    execute: (row) => approveConfigValue(row.latest_version_id),
    successMessage: '配置版本已审批，结果已记录审计。'
  }
];
const detailFields = [
  { prop: 'config_key', label: '配置键' },
  { prop: 'scope_type', label: '范围' },
  { prop: 'value_type', label: '值类型' },
  { prop: 'version', label: '当前版本' },
  { prop: 'value_summary', label: '值摘要' },
  { prop: 'latest_status', label: '状态' },
  { prop: 'latest_version_id', label: '版本记录 ID' },
  { prop: 'effective_at', label: '生效时间' }
];

const valuePlaceholder = computed(() => {
  const definition = definitions.value.find((item) => item.config_key === newConfig.config_key);
  if (!definition) return '字符串直接输入；JSON 请使用合法 JSON';
  if (definition.is_sensitive) return '{"reference":"placeholder://not-configured","masked_metadata":{}}';
  if (definition.value_type === 'json') return '{"example":true}';
  if (definition.value_type === 'boolean') return 'true 或 false';
  return `${definition.value_type || 'string'} 类型值`;
});

function unpack(response) {
  const data = response?.data || {};
  return Array.isArray(data.results) ? data.results : (Array.isArray(data.items) ? data.items : []);
}

function displayValue(value, definition) {
  if (definition?.is_sensitive) return '***';
  if (value === undefined || value === null) return '未创建';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function mapConnectedRows(definitionRows, versions) {
  return definitionRows.map((definition) => {
    const current = versions
      .filter((item) => item.config_key === definition.config_key)
      .sort((left, right) => Number(right.version || 0) - Number(left.version || 0))[0];
    return {
      ...definition,
      scope_type: definition.scope_type || definition.scope,
      version: current ? `v${current.version}` : '未创建',
      value_summary: current ? displayValue(current.value, definition) : displayValue(undefined, definition),
      latest_status: current?.status || 'not_configured',
      latest_version_id: current?.id || null,
      effective_at: current?.effective_at || '未设置',
      default_summary: displayValue(definition.default_value, definition)
    };
  });
}

async function loadConfigCenter(query = {}) {
  const definitionResponse = await fetchConfigDefinitions(query);
  if (!definitionResponse?.success) {
    apiStatus.value = definitionResponse?.http_status ? 'pending' : 'degraded';
    return definitionResponse;
  }
  const definitionRows = unpack(definitionResponse);
  definitions.value = definitionRows;
  if (definitionResponse.data?.api_status !== 'connected') {
    apiStatus.value = definitionResponse.data?.api_status || (useMock ? 'mock' : 'pending');
    return definitionResponse;
  }

  const valueResponse = await fetchConfigValues({ page: 1, page_size: 100, scope: query.scope || undefined });
  if (!valueResponse?.success) {
    apiStatus.value = valueResponse?.http_status ? 'pending' : 'degraded';
    return valueResponse;
  }
  apiStatus.value = 'connected';
  let rows = mapConnectedRows(definitionRows, unpack(valueResponse));
  if (query.scope) rows = rows.filter((row) => row.scope_type === query.scope);
  if (query.status) rows = rows.filter((row) => row.latest_status === query.status);
  const statusCount = (status) => rows.filter((row) => row.latest_status === status).length;
  return {
    ...definitionResponse,
    data: {
      api_status: 'connected',
      summary: [
        { label: '配置项', value: rows.length },
        { label: '生效中', value: statusCount('effective') },
        { label: '待审批', value: statusCount('pending_approval') },
        { label: '已批准', value: statusCount('approved') }
      ],
      items: rows
    }
  };
}

function openCreate() {
  if (!createAccess.value.allowed) {
    ElMessage.warning(createAccess.value.reason);
    return;
  }
  if (apiStatus.value !== 'connected') {
    ElMessage.info('配置接口尚未完成真实联调，当前不会发送写入请求。');
    return;
  }
  newConfig.config_key = definitions.value.find((item) => item.scope_type !== 'system' && item.scope !== 'system')?.config_key || definitions.value[0]?.config_key || '';
  newConfig.value = '';
  newConfig.effective_at = new Date().toISOString();
  createOpen.value = true;
}

function parseValue(raw, definition) {
  const value = String(raw ?? '').trim();
  if (!value) throw new Error('请填写配置值');
  if (definition?.is_sensitive || definition?.value_type === 'json') {
    try { return JSON.parse(value); } catch (_error) { throw new Error('JSON 配置值格式不合法'); }
  }
  if (definition?.value_type === 'integer') {
    const parsed = Number(value);
    if (!Number.isInteger(parsed)) throw new Error('配置值必须是整数');
    return parsed;
  }
  if (definition?.value_type === 'decimal') {
    if (!Number.isFinite(Number(value))) throw new Error('配置值必须是数字');
    return value;
  }
  if (definition?.value_type === 'boolean') {
    if (!['true', 'false'].includes(value.toLowerCase())) throw new Error('布尔配置值只能是 true 或 false');
    return value.toLowerCase() === 'true';
  }
  return raw;
}

async function submitCreate() {
  if (!createAccess.value.allowed || apiStatus.value !== 'connected') return;
  const definition = definitions.value.find((item) => item.config_key === newConfig.config_key);
  if (!definition) return ElMessage.warning('请选择配置项');
  let value;
  try { value = parseValue(newConfig.value, definition); } catch (error) { return ElMessage.warning(error.message); }
  creating.value = true;
  const response = await createConfigValue({
    config_key: newConfig.config_key,
    value,
    effective_at: newConfig.effective_at
  });
  creating.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '配置版本创建失败');
  ElMessage.success('配置版本已创建并记录审计');
  createOpen.value = false;
  await pageRef.value?.loadData();
}
</script>

<style scoped>
.config-form { margin-top: 16px; }
</style>
