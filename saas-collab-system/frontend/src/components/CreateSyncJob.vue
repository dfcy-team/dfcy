<template>
  <el-alert title="创建不执行：新任务默认为手动、停用。检查条件不访问真实平台。" type="info" :closable="false" show-icon />
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-form label-position="top" v-loading="loading">
    <el-form-item label="1. 店铺／仓库">
      <el-select v-model="subjectKey" filterable placeholder="选择店铺或仓库" @change="resetSelection">
        <el-option v-for="item in subjects" :key="item.key" :value="item.key" :label="`${item.platform} · ${item.subject_name} · #${item.subject_id}`" />
      </el-select>
    </el-form-item>
    <el-form-item v-if="subjectKey" label="2. 同步内容（可多选）">
      <el-checkbox-group v-model="selectedResources" @change="checked = false">
        <div v-for="resource in contents" :key="resource" class="resource-row">
          <el-checkbox :value="resource" :disabled="Boolean(existingJob(resource)) || !availableSources(resource).length">
            {{ resources[resource] || resource }}
          </el-checkbox>
          <el-button v-if="existingJob(resource)" link type="primary" @click="$emit('existing', existingJob(resource))">已有任务 #{{ existingJob(resource) }}</el-button>
          <span v-else-if="!availableSources(resource).length" class="resource-hint">{{ candidates(resource)[0]?.blockers?.join('；') || '暂无可用 API 来源' }}</span>
          <el-select v-else-if="selectedResources.includes(resource) && availableSources(resource).length > 1"
            v-model="sourceIds[resource]" class="source-select" placeholder="选择 API 来源" @change="checked = false">
            <el-option v-for="item in availableSources(resource)" :key="item.authorization_id" :value="item.authorization_id"
              :label="`${item.config_name} · 授权 #${item.authorization_id}`" />
          </el-select>
          <small v-else-if="selectedResources.includes(resource)" class="resource-hint">来源：{{ selectedSource(resource)?.config_name }}</small>
        </div>
      </el-checkbox-group>
    </el-form-item>
    <template v-if="selectedResources.length">
      <el-button :disabled="loading || saving" @click="check">3. 检查所选内容</el-button>
      <el-alert v-if="checked" type="success" title="本地条件检查通过；执行时仍须通过现有安全校验。" :closable="false" />
      <el-button type="primary" :disabled="!checked || loading" :loading="saving" @click="create">4. 创建 {{ selectedResources.length }} 个任务（不执行）</el-button>
    </template>
    <el-empty v-if="!loading && !items.length" description="当前权限范围内没有可用授权，请先配置店铺或仓库 API 接入。" />
  </el-form>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { requestApi } from '../api/request';
import { createSyncJob } from '../api/integrations';
import { resources, syncError } from '../utils/syncPresentation';

const emit = defineEmits(['created', 'existing']);
const items = ref([]), subjectKey = ref(''), selectedResources = ref([]), checked = ref(false);
const sourceIds = reactive({});
const loading = ref(false), saving = ref(false), error = ref('');
const key = item => `${item.subject_type}:${item.subject_id}`;
const subjects = computed(() => [...new Map(items.value.map(item => [key(item), { key: key(item), ...item }])).values()]);
const subjectItems = computed(() => items.value.filter(item => key(item) === subjectKey.value));
const contents = computed(() => [...new Set(subjectItems.value.map(item => item.resource_type))]);
const candidates = resource => subjectItems.value.filter(item => item.resource_type === resource);
const existingJob = resource => candidates(resource).find(item => item.existing_job_id)?.existing_job_id;
const availableSources = resource => candidates(resource).filter(item => !item.blockers.length && !item.existing_job_id);
const selectedSource = resource => availableSources(resource).find(item => item.authorization_id === sourceIds[resource])
  || (availableSources(resource).length === 1 ? availableSources(resource)[0] : null);

function resetSelection() {
  selectedResources.value = [];
  checked.value = false;
  error.value = '';
  Object.keys(sourceIds).forEach(resource => { delete sourceIds[resource]; });
}
async function load() {
  loading.value = true; error.value = '';
  try {
    const response = await requestApi({ method: 'get', url: '/api/internal/integrations/sync-jobs/missing-preview/', params: { include_existing: 'true' } });
    if (!response.success) throw new Error(response.message);
    items.value = response.data.items || [];
  } catch (e) { error.value = syncError(e.message); }
  finally { loading.value = false; }
}
async function check() {
  checked.value = false;
  if (!subjectKey.value || !selectedResources.value.length) return;
  const prior = Object.fromEntries(selectedResources.value.map(resource => [resource, selectedSource(resource)?.authorization_id]));
  await load();
  if (error.value) return;
  for (const resource of selectedResources.value) {
    if (!prior[resource]) {
      error.value = `请为${resources[resource] || resource}选择 API 来源。`;
      return;
    }
    const item = candidates(resource).find(candidate => candidate.authorization_id === prior[resource]);
    if (!item || item.existing_job_id || item.blockers.length || existingJob(resource)) {
      error.value = `${resources[resource] || resource} 的 API 来源已变化或不再可用，请重新选择。`;
      return;
    }
  }
  checked.value = true;
}
async function create() {
  if (saving.value || !checked.value || !selectedResources.value.length) return;
  saving.value = true; checked.value = false; error.value = '';
  const ids = [];
  const planned = selectedResources.value.map(resource => selectedSource(resource));
  try {
    for (const item of planned) {
      if (!item || item.blockers.length || item.existing_job_id || existingJob(item.resource_type)) throw new Error('所选内容已变化，请重新检查。');
      const response = await createSyncJob({
        integration_config_id: item.integration_config_id,
        [`${item.subject_type}_authorization_id`]: item.authorization_id,
        resource_type: item.resource_type, schedule_type: 'manual', is_enabled: false,
      });
      if (!response.success) throw new Error(response.message);
      ids.push(response.data.job?.id || response.data.id);
    }
    emit('created', { count: ids.length, ids });
  } catch (e) {
    await load();
    selectedResources.value = selectedResources.value.filter(resource => !existingJob(resource));
    error.value = `${ids.length ? `已创建 ${ids.length} 个任务；` : ''}${syncError(e.message)}。请检查剩余内容后重试。`;
  } finally { saving.value = false; }
}
onMounted(load);
</script>
<style scoped>
.el-form { margin-top: 16px; } .el-select { width: 100%; } .el-alert { margin: 12px 0; }
.resource-row { display: flex; align-items: center; gap: 12px; min-height: 42px; flex-wrap: wrap; }
.source-select { width: min(300px, 100%); } .resource-hint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
