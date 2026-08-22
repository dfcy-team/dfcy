<template>
  <Stage0Placeholder
    title="数据同步与质量"
    api-path="pending: sales_management.data_quality"
    :fields="['平台', '区域', '门店', '授权引用状态', '最近成功时间', '最近运行状态', '同步水位', '数据延迟', '质量问题数', '错误摘要']"
    :search-fields="['平台', '区域', '门店', '同步状态', '质量问题类型', '时间范围']"
    :actions="['查看运行详情占位', '查看错误占位', '下载脱敏错误报告占位', '申请手工重跑占位']"
    :extra-items="['问题类型：重复订单、金额不平、退款未回补、SKU 未映射、币种/时区缺失、迟到数据', '手工重跑仅提交申请，必须幂等并写审计', '不展示 App Secret、access token、refresh token']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
