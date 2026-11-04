<template>
  <div v-if="storeId && visible.length" class="registration-links">
    <el-button v-for="entry in visible" :key="entry.path" @click="router.push({ path: entry.path, query: { store_id: String(storeId), ...(orderNumber ? { order_number: orderNumber } : {}) } })">{{ entry.label }}</el-button>
  </div>
</template>
<script setup>
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { canAccessPath } from '../router/menu';
defineProps({ storeId: { type: [Number, String], default: null }, orderNumber: { type: String, default: '' } });
const router = useRouter(), auth = useAuthStore();
const entries = [{ path: '/sales/pre-shipment-adjustments', label: '相关换货登记' }, { path: '/sales/special-order-registrations', label: '相关订单推广登记' }, { path: '/finance/gcash-refunds', label: '相关GCash退款登记' }];
const visible = computed(() => entries.filter(entry => canAccessPath(auth.currentUser, entry.path)));
</script>
<style scoped>.registration-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }</style>
