<template>
  <el-form-item v-if="!freight" label="首次合作日期">
    <el-date-picker
      v-model="form.first_cooperation_date"
      type="date"
      value-format="YYYY-MM-DD"
      clearable
      :disabled="disabled"
      placeholder="选择首次合作日期"
    />
  </el-form-item>
  <el-form-item v-if="!freight" label="默认对公税点 (%)">
    <el-input-number v-model="form.default_tax_rate" :min="0" :max="100" :step="0.001" :precision="3" :disabled="disabled" controls-position="right" placeholder="未维护" />
    <el-button v-if="form.default_tax_rate != null" link :disabled="disabled" @click="form.default_tax_rate = null">清空</el-button>
  </el-form-item>
  <el-form-item label="账期天数">
    <el-input-number
      v-model="form.payment_term_days"
      :min="0"
      :max="3650"
      :step="1"
      :precision="0"
      :disabled="disabled"
      controls-position="right"
      placeholder="未维护"
    />
  </el-form-item>
  <el-form-item label="账期起算方式">
    <el-select v-model="form.payment_term_start" :disabled="disabled" placeholder="请选择">
      <el-option v-for="option in paymentTermStarts" :key="option.value" :label="option.label" :value="option.value" />
    </el-select>
  </el-form-item>
  <el-form-item label="提前提醒天数">
    <el-input-number v-model="form.payment_reminder_days" :min="0" :max="365" :precision="0" :disabled="disabled" />
    <small>例如填 7：到期前 7 天进入提醒；0 为到期当天。</small>
  </el-form-item>
</template>

<script setup>
defineProps({ form: { type: Object, required: true }, disabled: { type: Boolean, default: false }, freight: Boolean });

const paymentTermStarts = [
  { label: '未约定', value: 'unspecified' },
  { label: '供应商发货日', value: 'shipment_date' },
  { label: '集货到仓日', value: 'collection_arrival' },
  { label: '目的仓到仓日', value: 'warehouse_arrival' },
  { label: '对账确认日', value: 'reconciliation_date' },
];
</script>
