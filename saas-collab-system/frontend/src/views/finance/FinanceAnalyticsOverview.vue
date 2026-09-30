<template>
  <section>
    <header class="finance-links">
      <span>财务分析</span
      ><BusinessDashboardLink module="财务中心" /><el-button
        v-for="link in links"
        :key="link.path"
        v-show="canAccessPath(auth.currentUser, link.path)"
        @click="router.push(link.path)"
        >{{ link.label }}</el-button
      >
    </header>
    <el-tabs v-model="tab"
      ><el-tab-pane label="平台流水与费用" name="finance" /><el-tab-pane
        label="库存估值与成本覆盖"
        name="inventory_value"
    /></el-tabs>
    <ReportWorkbench :dataset="tab" />
    <p class="note">订单利润、结算利润和实际回款将在相应数据链路完整后开放；当前流水净额与库存货值不能代替利润。</p>
  </section>
</template>
<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import ReportWorkbench from '../reports/ReportWorkbench.vue';
import BusinessDashboardLink from '../reports/BusinessDashboardLink.vue';
const tab = ref('finance'),
  router = useRouter(),
  auth = useAuthStore();
const links = [
  { path: '/finance/statements', label: '平台账单' },
  { path: '/finance/reconciliation/matches', label: '对账差异' },
  { path: '/finance/reconciliation/exceptions', label: '对账异常' }
];
</script>
<style scoped>
.finance-links {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.finance-links span {
  font-size: 18px;
  margin-right: auto;
}
.note {
  font-size: 12px;
  color: #526177;
  line-height: 1.7;
}
</style>
