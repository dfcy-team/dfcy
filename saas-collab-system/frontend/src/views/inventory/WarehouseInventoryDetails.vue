<template>
  <RecoveredWarehousePanel537 v-if="canViewProducts" kind="category" title="仓库库存明细" />
  <InventoryWorkbench v-else-if="canViewExceptions" warehouse-details />
</template>

<script setup>
import { computed } from 'vue';
import { canAccessPath, canAccessWarehouseExceptions } from '../../router/menu';
import { useAuthStore } from '../../stores/auth';
import RecoveredWarehousePanel537 from '../../components/inventory/RecoveredWarehousePanel537.js';
import InventoryWorkbench from './InventoryWorkbench.vue';

const auth = useAuthStore();
const canViewExceptions = computed(() => canAccessWarehouseExceptions(auth.currentUser));
const canViewProducts = computed(() => canAccessPath(auth.currentUser, '/inventory/category-query'));
</script>

