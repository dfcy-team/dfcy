<template>
  <section class="inventory-warning-entry">
    <el-tabs v-model="tab" aria-label="库存预警视图">
      <el-tab-pane label="库存风险" name="risk"><InventoryWarningRisk537 v-if="tab === 'risk'" /></el-tab-pane>
      <el-tab-pane label="原有预警跟进" name="followup"><InventoryAlertFollowup537 v-if="tab === 'followup'" /></el-tab-pane>
    </el-tabs>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { cockpitActorKey } from '../../utils/cockpitDraft';
import InventoryAlertFollowup537 from './InventoryAlertFollowup537.vue';
import InventoryWarningRisk537 from './InventoryWarningRisk537.vue';
const auth=useAuthStore();
const requiredRiskCodes=['alerts.view','sales_management.view','sales_management.skus.view','sales_management.supply_summary.view'];
const canDefaultRisk=computed(()=>!auth.authorizationStale && (auth.isSuperuser===true || auth.currentUser?.is_superuser===true || requiredRiskCodes.every(code=>auth.hasPermission?.(code)&&auth.hasAllDataScopeFor?.(code))));
const tab=ref(canDefaultRisk.value?'risk':'followup');
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale,canDefaultRisk.value],([owner,stale,allowed],previous)=>{
  if(owner!==previous?.[0] || stale || !allowed)tab.value=allowed&&!stale?'risk':'followup';
},{flush:'sync'});
</script>
