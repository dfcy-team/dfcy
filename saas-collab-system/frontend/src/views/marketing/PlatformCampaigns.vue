<template>
  <FlashSalesWorkspace v-if="inFlash" @back="back" />
  <section v-else class="campaign-entry">
    <h1>平台活动</h1>
    <p>选择活动类型，管理店铺活动与执行结果。</p>
    <article v-if="canViewFlash" class="campaign-card">
      <small>Shopee 店铺营销</small><h2>店内闪购</h2>
      <p>按店铺配置补建闪购，管理平台活动并查看执行记录。</p>
      <p>店铺运行 · 活动管理 · 执行记录</p>
      <el-button type="primary" @click="enter">进入店内闪购</el-button>
    </article>
    <el-empty v-else description="暂无平台活动" />
  </section>
</template>

<script setup>
import FlashSalesWorkspace from './FlashSalesWorkspace.vue';
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
const route = useRoute(), router = useRouter();
const auth = useAuthStore();
const canViewFlash = computed(() => auth.hasPermission('marketing.flash_sales.view'));
const inFlash = computed(() => canViewFlash.value && (route.query.activity === 'flash' || Boolean(route.query.tab || route.query.batch)));
function enter() {router.push({query:{...route.query,activity:'flash',tab:'stores'}});}
function back() {const {activity,tab,batch,...query} = route.query;router.push({query});}
</script>

<style scoped>
.campaign-entry {padding:24px}.campaign-entry h1 {font-size:24px}.campaign-entry p {color:var(--el-text-color-secondary);line-height:1.7}.campaign-card {margin-top:24px;padding:24px;border:1px solid var(--el-border-color);border-radius:8px;max-width:520px;background:var(--el-bg-color)}.campaign-card small {color:var(--el-text-color-secondary)}
</style>
