<template>
  <el-select v-if="choices" :model-value="modelValue" clearable :placeholder="filterKey === 'sku_mode' ? '选择商品编码口径' : '全部'" @update:model-value="update">
    <el-option v-for="item in choices" :key="item.value" :label="item.label" :value="item.value" />
  </el-select>
  <div v-else-if="filterKey === 'store_id'" class="store-filter">
    <el-select :model-value="modelValue == null ? '' : String(modelValue)" filterable remote clearable reserve-keyword
      :remote-method="searchStores" :loading="loading" placeholder="搜索门店名称、编码或编号" @update:model-value="update">
      <el-option v-for="item in options" :key="item.value" :label="item.label" :value="item.value" />
      <template #empty><span>{{ loading ? '正在读取门店…' : error ? '门店读取失败' : '没有匹配门店' }}</span></template>
    </el-select>
    <small v-if="hasMore && !error" class="store-filter__hint">已显示前 100 项，请输入名称、编码或编号继续筛选。</small>
    <div v-if="error" class="store-filter__error" role="alert"><span>{{ error }}</span><el-button link type="primary" @click="retry">重试</el-button></div>
  </div>
  <el-select v-else-if="options.length" :model-value="modelValue == null ? '' : String(modelValue)" filterable allow-create default-first-option clearable placeholder="选择当前结果中的项目，或输入编号" @update:model-value="update"><el-option v-for="item in options" :key="item.value" :label="item.label" :value="item.value" /></el-select>
  <el-date-picker v-else-if="filterKey.startsWith('date_') || filterKey === 'mapping_as_of'" :model-value="modelValue" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" clearable @update:model-value="update" />
  <el-input v-else :model-value="modelValue" :placeholder="filterKey === 'currency' ? '输入币种，如 CNY' : filterKey.includes('ids') || filterKey === 'platforms' ? '多项用逗号分隔' : '全部'" clearable @update:model-value="update" />
</template>
<script setup>
import { computed } from 'vue';
import { filterChoices } from './reportDisplay';
const props = defineProps({ filterKey: { type: String, required: true }, modelValue: { default: '' }, options: { type: Array, default: () => [] }, loading: { type: Boolean, default: false }, error: { type: String, default: '' }, hasMore: { type: Boolean, default: false } });
const emit = defineEmits(['update:modelValue', 'search', 'retry']);
const choices = computed(() => filterChoices[props.filterKey]);
const update = value => emit('update:modelValue', value);
const searchStores = value => emit('search', value || '');
const retry = () => emit('retry');
</script>
<style scoped>
.store-filter { display: grid; gap: 4px; }
.store-filter__hint { color: #64748b; font-size: 12px; line-height: 1.4; }
.store-filter__error { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #b42318; font-size: 12px; }
</style>
