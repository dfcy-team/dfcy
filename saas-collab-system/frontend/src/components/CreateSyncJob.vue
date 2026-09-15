<template>
  <el-alert title="创建不执行：新任务默认为手动、停用。检查条件不访问真实平台。" type="info" :closable="false" show-icon />
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-form label-position="top" v-loading="loading">
    <el-form-item label="1. 平台和接入配置">
      <el-select v-model="configId" filterable @change="subjectKey = ''; selected = null; checked = false">
        <el-option v-for="item in configs" :key="item.integration_config_id" :value="item.integration_config_id" :label="`${item.platform} · ${item.config_name} #${item.integration_config_id}`" />
      </el-select>
    </el-form-item>
    <el-form-item label="2. 店铺／仓库">
      <el-select v-model="subjectKey" filterable :disabled="!configId" @change="selected = null; checked = false">
        <el-option v-for="item in subjects" :key="key(item)" :value="key(item)" :label="item.subject_name" />
      </el-select>
    </el-form-item>
    <el-form-item label="3. 同步内容">
      <el-select v-model="selected" value-key="resource_type" :disabled="!subjectKey" @change="checked = false">
        <el-option v-for="item in contents" :key="item.resource_type" :value="item" :label="resources[item.resource_type] || item.resource_type" />
      </el-select>
    </el-form-item>
    <template v-if="selected">
      <el-alert v-if="selected.existing_job_id" title="已有同类任务，不会重复创建。" type="info" :closable="false" />
      <el-button v-if="selected.existing_job_id" @click="$emit('existing', selected.existing_job_id)">查看已有任务 #{{ selected.existing_job_id }}</el-button>
      <template v-else>
        <el-button :disabled="loading || saving" @click="check">4. 检查条件</el-button>
        <el-alert v-if="checked" :type="selected.blockers.length ? 'warning' : 'success'" :title="selected.blockers.join('；') || '本地条件检查通过；执行时仍须通过现有安全校验。'" :closable="false" />
        <el-button type="primary" :disabled="!checked || selected.blockers.length > 0" :loading="saving" @click="create">5. 确认创建（不执行）</el-button>
      </template>
    </template>
    <el-empty v-if="!loading && !items.length" description="当前权限范围内没有可用授权，请先配置店铺或仓库 API 接入。" />
  </el-form>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue';
import { requestApi } from '../api/request';
import { createSyncJob } from '../api/integrations';
import { resources, syncError } from '../utils/syncPresentation';
const emit = defineEmits(['created', 'existing']);
const items = ref([]), configId = ref(null), subjectKey = ref(''), selected = ref(null), checked = ref(false);
const loading = ref(false), saving = ref(false), error = ref('');
const key = item => `${item.subject_type}:${item.authorization_id}`;
const configs = computed(() => [...new Map(items.value.map(item => [item.integration_config_id, item])).values()]);
const subjects = computed(() => [...new Map(items.value.filter(item => item.integration_config_id === configId.value).map(item => [key(item), item])).values()]);
const contents = computed(() => items.value.filter(item => item.integration_config_id === configId.value && key(item) === subjectKey.value));
async function load() {
  loading.value = true; error.value = '';
  try {
    const response = await requestApi({ method: 'get', url: '/api/internal/integrations/sync-jobs/missing-preview/', params: { include_existing: 'true' } });
    if (!response.success) throw new Error(response.message);
    items.value = response.data.items;
  } catch (e) { error.value = syncError(e.message); }
  finally { loading.value = false; }
}
async function check() {
  const resource = selected.value.resource_type;
  checked.value = false;
  await load();
  if (error.value) return;
  selected.value = contents.value.find(item => item.resource_type === resource) || null;
  checked.value = Boolean(selected.value);
}
async function create() {
  if (saving.value || !checked.value || !selected.value || selected.value.blockers.length || selected.value.existing_job_id) return;
  saving.value = true; error.value = '';
  try {
    const item = selected.value;
    const response = await createSyncJob({ integration_config_id: item.integration_config_id, [`${item.subject_type}_authorization_id`]: item.authorization_id, resource_type: item.resource_type, schedule_type: 'manual', is_enabled: false });
    if (!response.success) throw new Error(response.message);
    emit('created', response.data.job?.id || response.data.id);
  } catch (e) { error.value = syncError(e.message); checked.value = false; }
  finally { saving.value = false; }
}
onMounted(load);
</script>
<style scoped>
.el-form { margin-top: 16px; } .el-select { width: 100%; } .el-alert { margin: 12px 0; }
</style>
