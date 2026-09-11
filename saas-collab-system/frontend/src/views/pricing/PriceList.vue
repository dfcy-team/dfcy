<template>
  <section class="price-page" :aria-busy="loading">
    <header><div><h1>价格中心</h1><p>查看 SKU 建议价格与审批状态；当前尚未接入真实价格服务。</p></div><el-tag :type="error ? 'danger' : 'info'">{{ error ? '读取失败' : state === 'mock' ? '模拟数据' : '待接入' }}</el-tag></header>
    <el-alert title="价格接口尚未实现，不提供真实建议价；价格审批和应用操作保持禁用，不会修改平台价格。" type="info" show-icon :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <section class="price-table">
      <h2>建议价格</h2><p>金额按行内币种展示，保留两位小数；“—”表示未提供，不是零价格。</p>
      <el-table v-loading="loading" :data="rows" stripe empty-text="真实价格数据尚未接入，暂时没有可展示的价格记录。">
        <el-table-column prop="sku" label="SKU 编码" min-width="200" show-overflow-tooltip />
        <el-table-column prop="currency" label="币种" min-width="100" />
        <el-table-column label="建议价格" min-width="160" align="right"><template #default="{ row }">{{ formatField(row.suggested_price, { format: 'money' }) }}</template></el-table-column>
        <el-table-column label="审批状态" min-width="140"><template #default="{ row }"><el-tag :type="statusType(row.approval_status)">{{ statusLabel(row.approval_status) }}</el-tag></template></el-table-column>
      </el-table>
    </section>
    <div><el-button disabled>提交价格审批（待接入）</el-button><el-button disabled>应用清仓价（待接入）</el-button></div>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { fetchPrices } from '../../api/pricing';
import { formatApiError } from '../../api/request';
import { collectionRows, apiState } from '../../utils/businessResponse';
import { formatField, statusLabel, statusType } from '../sales-management/display';
const loading = ref(false), rows = ref([]), state = ref('pending'), error = ref('');
onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchPrices();
    if (!response.success) { error.value = formatApiError(response); return; }
    state.value = apiState(response.data, 'pending');
    rows.value = state.value === 'mock' ? collectionRows(response.data) : [];
  } catch (err) { error.value = formatApiError({ message: err?.message }); }
  finally { loading.value = false; }
});
</script>
<style scoped>
.price-page { display: grid; gap: 16px; color: #172033; }
header { display: flex; justify-content: space-between; gap: 16px; }
h1 { margin: 0; font-size: 26px; } h2 { margin: 0; font-size: 16px; }
p { color: #475569; line-height: 1.6; font-size: 13px; }
.price-table { min-width: 0; padding: 18px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; font-variant-numeric: tabular-nums; }
</style>
