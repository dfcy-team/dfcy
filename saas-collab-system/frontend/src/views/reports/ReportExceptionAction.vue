<template>
  <el-dialog :model-value="modelValue" title="发起报表核查" width="min(520px, 94vw)" @update:model-value="$emit('update:modelValue', $event)">
    <p>保存当前分组、查询范围与指标口径，进入异常中心分配负责人。提交时重新核对业务权限。</p>
    <p class="note">{{ queryScope(config).join(' · ') }}</p>
    <el-form label-position="top"><el-form-item label="核查事项"><el-input v-model="title" maxlength="200" placeholder="说明需要负责人核查的问题" /></el-form-item></el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template #footer><el-button @click="$emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="loading" :disabled="!title.trim()" @click="submit">创建核查事项</el-button></template>
  </el-dialog>
</template>
<script setup>
import { ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { createReportException } from '../../api/reportCollaboration';
import { queryScope } from './reportContext';
import { reportError } from './reportDisplay';
const props = defineProps({ modelValue: Boolean, config: Object, group: Object });
const emit = defineEmits(['update:modelValue']);
const router = useRouter(), title = ref(''), error = ref(''), loading = ref(false);
let requestKey, requestPayload;
watch(() => props.modelValue, value => { if (value) { title.value = '报表分组核查'; error.value = ''; requestKey = crypto.randomUUID(); requestPayload = undefined; } }, { immediate: true });
async function submit() {
  if (loading.value || !title.value.trim() || !props.config || !props.group) return;
  loading.value = true; error.value = '';
  try {
    const group = Object.fromEntries(props.config.dimensions.map(key => [key, props.group[key] ?? null]));
    const payload = { config: props.config, group, title: title.value.trim() };
    const fingerprint = JSON.stringify(payload);
    if (fingerprint !== requestPayload) { requestKey = crypto.randomUUID(); requestPayload = fingerprint; }
    const response = await createReportException({ ...payload, request_key: requestKey });
    if (!response.success) throw new Error(response.message);
    emit('update:modelValue', false);
    router.push(`/workflow/exceptions/${response.data.id}`);
  } catch (failure) { error.value = reportError(failure.message, '创建核查失败，请重试。'); }
  finally { loading.value = false; }
}
</script>
<style scoped>p { color: #526177; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }.note { font-size: 12px; }</style>
