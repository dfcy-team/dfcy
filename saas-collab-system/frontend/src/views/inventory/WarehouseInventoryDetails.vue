<template>
  <el-tabs v-if="canViewProducts && canViewExceptions" v-model="tab" aria-label="仓库库存明细查询">
    <el-tab-pane label="整款库存" name="products" lazy>
      <CategoryInventory embedded />
    </el-tab-pane>
    <el-tab-pane label="库存异常清单" name="exceptions" lazy>
      <InventoryWorkbench warehouse-details />
    </el-tab-pane>
  </el-tabs>
  <CategoryInventory v-else-if="canViewProducts" embedded />
  <InventoryWorkbench v-else-if="canViewExceptions" warehouse-details />
</template>

<script setup>
import { computed, ref } from 'vue';
import { canAccessPath, canAccessWarehouseExceptions } from '../../router/menu';
import { useAuthStore } from '../../stores/auth';
import CategoryInventory from './CategoryInventory.vue';
import InventoryWorkbench from './InventoryWorkbench.vue';

const auth = useAuthStore();
const tab = ref('products');
const canViewExceptions = computed(() => canAccessWarehouseExceptions(auth.currentUser));
const canViewProducts = computed(() => canAccessPath(auth.currentUser, '/inventory/category-query'));
</script>
