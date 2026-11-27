<template>
  <section class="inventory-warning-entry">
    <InventoryWarningRisk537 v-if="canDefaultRisk" />
    <el-empty v-else description="当前账号暂无查看库存风险的完整授权范围" />
  </section>
</template>
<script setup>
import { computed } from 'vue';
import { useAuthStore } from '../../stores/auth';
import InventoryWarningRisk537 from './InventoryWarningRisk537.vue';
const auth=useAuthStore();
const requiredRiskCodes=['alerts.view','sales_management.view','sales_management.skus.view','sales_management.supply_summary.view'];
const canDefaultRisk=computed(()=>!auth.authorizationStale && (auth.isSuperuser===true || auth.currentUser?.is_superuser===true || requiredRiskCodes.every(code=>auth.hasPermission?.(code)&&auth.hasAllDataScopeFor?.(code))));
</script>
