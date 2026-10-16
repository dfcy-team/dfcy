<template>
  <div class="table-scroll">
    <el-table :data="lines" border empty-text="暂无商品明细">
      <el-table-column label="商品图片" width="112"><template #default="{row}"><DocumentProductImageV2 :image-path="row.image_preview_url || ''" :alt="`${row.sku} 商品图片`"/></template></el-table-column>
      <el-table-column label="SKU" min-width="190"><template #default="{row}"><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code"/></template></el-table-column>
      <el-table-column prop="product_name" label="商品" min-width="160"/>
      <el-table-column prop="quantity" :label="hasBatchAllocation?'本批数量':'发货数量'" width="100"/>
      <el-table-column v-if="hasBatchAllocation" prop="source_quantity" label="原发货量" width="100"/>
      <el-table-column v-if="hasBatchAllocation" prop="remaining_quantity" label="当前未分配" width="100"/>
      <el-table-column v-if="hasBatchAllocation" prop="available_quantity" label="本批可用量" width="100"/>
      <el-table-column prop="shipment_number" label="发货单" min-width="150"/>
      <el-table-column prop="supplier_name" label="供应商" min-width="130"/>
    </el-table>
  </div>
</template>
<script setup>
import { computed } from 'vue';
import DocumentProductImageV2 from './DocumentProductImageV2.vue';
import DocumentSkuV2 from './DocumentSkuV2.vue';
const props = defineProps({ shipments: { type: Array, default: () => [] } });
const hasBatchAllocation = computed(() => props.shipments.some(shipment => (shipment.lines || []).some(line => line.source_quantity != null)));
const lines = computed(() => props.shipments.flatMap(shipment => (shipment.lines || []).map(line => ({
  ...line, shipment_number: shipment.number, supplier_name: shipment.supplier_name,
}))));
</script>
<style scoped>.table-scroll{max-width:100%;overflow-x:auto}</style>
