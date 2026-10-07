<template>
  <el-select v-if="choices" :model-value="modelValue" clearable :placeholder="filterKey === 'sku_mode' ? '选择商品编码口径' : '全部'" @update:model-value="update">
    <el-option v-for="item in choices" :key="item.value" :label="item.label" :value="item.value" />
  </el-select>
  <el-select v-else-if="options.length" :model-value="modelValue == null ? '' : String(modelValue)" filterable allow-create default-first-option clearable placeholder="选择当前结果中的项目，或输入编号" @update:model-value="update"><el-option v-for="item in options" :key="item.value" :label="item.label" :value="item.value" /></el-select>
  <el-date-picker v-else-if="filterKey.startsWith('date_') || filterKey === 'mapping_as_of'" :model-value="modelValue" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" clearable @update:model-value="update" />
  <el-input v-else :model-value="modelValue" :placeholder="filterKey === 'currency' ? '输入币种，如 CNY' : filterKey.includes('ids') || filterKey === 'platforms' ? '多项用逗号分隔' : '全部'" clearable @update:model-value="update" />
</template>
<script setup>
import { computed } from 'vue';
import { filterChoices } from './reportDisplay';
const props = defineProps({ filterKey: { type: String, required: true }, modelValue: { default: '' }, options: { type: Array, default: () => [] } });
const emit = defineEmits(['update:modelValue']);
const choices = computed(() => filterChoices[props.filterKey]);
const update = value => emit('update:modelValue', value);
</script>
