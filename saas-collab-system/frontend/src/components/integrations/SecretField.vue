<template>
  <div class="secret-field">
    <div class="secret-state">
      <span class="secret-label">{{ label }}</span>
      <el-tag :type="configured ? 'success' : 'info'" size="small">
        {{ configured ? '******** · 已配置' : '未配置' }}
      </el-tag>
    </div>
    <div v-if="editing" class="secret-input-row">
      <el-input
        :model-value="modelValue"
        :type="revealed ? 'text' : 'password'"
        autocomplete="new-password"
        placeholder="输入新值；保存后不会再次显示"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <el-button text @click="revealed = !revealed">{{ revealed ? '隐藏' : '显示本次输入' }}</el-button>
      <el-button text @click="cancel">取消</el-button>
    </div>
    <el-button v-else text type="primary" @click="editing = true">{{ configured ? '替换' : '配置' }}</el-button>
  </div>
</template>

<script setup>
import { ref } from 'vue';

defineProps({
  label: { type: String, required: true },
  modelValue: { type: String, default: '' },
  configured: { type: Boolean, default: false }
});
const emit = defineEmits(['update:modelValue']);
const editing = ref(false);
const revealed = ref(false);

function cancel() {
  emit('update:modelValue', '');
  editing.value = false;
  revealed.value = false;
}
</script>

<style scoped>
.secret-field { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(280px, 2fr); gap: 16px; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.secret-state { display: flex; align-items: center; gap: 12px; }
.secret-label { font-weight: 600; color: var(--el-text-color-primary); }
.secret-input-row { display: flex; align-items: center; gap: 8px; }
@media (max-width: 760px) { .secret-field { grid-template-columns: 1fr; } .secret-input-row { flex-wrap: wrap; } }
</style>
