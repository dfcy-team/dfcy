<template>
  <section class="influencer-workspace">
    <header class="workspace-heading">
      <div>
        <span>CREATOR OPERATIONS</span>
        <h1>BD 绩效</h1>
        <p>按日期范围查看达人开拓、送样投入与合作产出。</p>
      </div>
      <div class="source-note">
        <i />
        绩效聚合数据已接入
      </div>
    </header>

    <BdPerformancePanel />
  </section>
</template>

<script setup>
import BdPerformancePanel from './BdPerformancePanel.vue';
</script>

<style scoped>
.influencer-workspace { display: grid; gap: 16px; min-width: 0; }
.workspace-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.workspace-heading span { color: #5e6f7c; font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.workspace-heading h1 { margin: 3px 0 4px; color: #16232d; font-size: 24px; line-height: 1.2; }
.workspace-heading p { margin: 0; color: #687884; font-size: 13px; }
.source-note { display: inline-flex; align-items: center; gap: 7px; margin-top: 7px; padding: 6px 10px; border: 1px solid #dce4e9; border-radius: 7px; background: #fff; color: #60717d; font-size: 12px; white-space: nowrap; }
.source-note i { width: 7px; height: 7px; border-radius: 50%; background: #14936f; box-shadow: 0 0 0 3px #e0f3ed; }
@media (max-width: 760px) {
  .workspace-heading { display: grid; gap: 8px; }
}
</style>
