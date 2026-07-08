<template>
  <Stage0Placeholder title="RPA任务详情" api-path="pending: rpa.tasks.detail" :fields="fields" :search-fields="['任务编号']" :actions="['重试按钮占位', '人工接管按钮占位']" :extra-items="extraItems" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['任务编号', '任务类型', '业务类型', '业务ID', 'Agent', '状态', '重试次数', 'payload JSON展示', 'result JSON展示', '步骤日志', '截图列表', '错误原因', '重试按钮占位', '人工接管按钮占位'];
const extraItems = ['pending', 'claimed', 'running', 'success', 'failed', 'retrying', 'manual_required', 'cancelled', 'BIGSELLER_CREATE_PRODUCT', 'BIGSELLER_UPLOAD_IMAGES', 'BIGSELLER_MULTI_SITE_LISTING', 'BIGSELLER_UPDATE_PRICE', 'BIGSELLER_READ_PAGE_PRICE', 'BIGSELLER_COLLECT_LISTING_STATUS'];
</script>
