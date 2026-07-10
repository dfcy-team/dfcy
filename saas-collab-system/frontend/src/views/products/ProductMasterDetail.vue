<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">商品主数据详情</h1>
        <p>API: GET /api/internal/products/spus/{id}/；POST /api/internal/products/spus/{id}/freeze-code/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>基础属性</template>
      <el-form :model="detail" label-width="130px">
        <el-form-item label="SPU"><el-input :model-value="detail.spu_code" disabled /></el-form-item>
        <el-form-item label="商品名称"><el-input :model-value="detail.product_name" disabled /></el-form-item>
        <el-form-item label="类目"><el-input :model-value="detail.category" disabled /></el-form-item>
        <el-form-item label="生命周期状态"><el-input :model-value="detail.lifecycle_status" disabled /></el-form-item>
        <el-form-item label="销售状态"><el-input :model-value="detail.sales_status" disabled /></el-form-item>
        <el-form-item label="编码冻结"><el-input :model-value="detail.is_code_frozen ? '已冻结' : '未冻结'" disabled /></el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>SKU资料</template>
      <el-table :data="relatedSkus" border empty-text="暂无SKU数据">
        <el-table-column prop="sku_code" label="SKU" min-width="150" />
        <el-table-column prop="size" label="尺码" min-width="100" />
        <el-table-column prop="material" label="材质" min-width="120" />
        <el-table-column label="卖点" min-width="180">
          <template #default="{ row }">{{ formatList(row.selling_points) }}</template>
        </el-table-column>
        <el-table-column prop="package_weight" label="箱规重量" min-width="110" />
        <el-table-column prop="package_volume" label="箱规体积" min-width="110" />
        <el-table-column label="编码冻结" min-width="100">
          <template #default="{ row }">{{ row.is_code_frozen ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>图片/附件占位</template>
      <el-upload action="#" disabled><el-button disabled>选择附件占位</el-button></el-upload>
    </el-card>

    <div class="fix-actions">
      <el-button disabled>保存占位</el-button>
      <el-button type="primary" :disabled="loading || !detail.id || detail.is_code_frozen" :loading="freezing" @click="handleFreeze">
        编码冻结
      </el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchProductMasterDetail, fetchProductSkuList, freezeProductCode } from '../../api/products';

const route = useRoute();
const detail = ref({});
const skus = ref([]);
const loading = ref(false);
const freezing = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));
const relatedSkus = computed(() => skus.value.filter((sku) => sku.spu === detail.value.id));

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

function formatList(value) {
  return Array.isArray(value) ? value.join(', ') : value || '-';
}

async function loadDetail() {
  loading.value = true;
  try {
    const [detailResponse, skuResponse] = await Promise.all([
      fetchProductMasterDetail(route.params.id || 1),
      fetchProductSkuList()
    ]);
    if (!detailResponse.success) throw new Error(detailResponse.message || 'SPU详情接口失败');
    if (!skuResponse.success) throw new Error(skuResponse.message || 'SKU接口失败');
    detail.value = getDetail(detailResponse.data);
    skus.value = getRows(skuResponse.data);
    status.value = detailResponse.data?.api_status || detailResponse.data?.status || 'api';
    if (detailResponse.data?.api_status === 'fallback' || skuResponse.data?.api_status === 'fallback') {
      message.value = detailResponse.message || skuResponse.message;
      status.value = 'fallback';
    }
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '商品详情请求失败';
  } finally {
    loading.value = false;
  }
}

async function handleFreeze() {
  freezing.value = true;
  try {
    const response = await freezeProductCode(detail.value.id);
    if (!response.success) throw new Error(response.message || '编码冻结接口失败');
    detail.value = { ...detail.value, ...getDetail(response.data), is_code_frozen: true };
    status.value = response.data?.api_status || response.data?.status || status.value;
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '编码冻结请求失败';
  } finally {
    freezing.value = false;
  }
}

onMounted(loadDetail);
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.fix-actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
