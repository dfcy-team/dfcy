<template>
  <section class="product-page">
    <header class="product-header">
      <div>
        <h1 class="page-title">商品主数据详情</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/products/spus/{id}/，GET /api/internal/products/skus/，POST /api/internal/products/spus/{id}/freeze-code/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>基础属性</template>
      <el-form :model="detail" label-width="120px">
        <el-form-item label="SPU"><el-input :model-value="detail.spu_code" disabled /></el-form-item>
        <el-form-item label="商品名称"><el-input :model-value="detail.product_name" disabled /></el-form-item>
        <el-form-item label="类目"><el-input :model-value="detail.category" disabled /></el-form-item>
        <el-form-item label="生命周期状态"><el-input :model-value="detail.lifecycle_status" disabled /></el-form-item>
        <el-form-item label="销售状态"><el-input :model-value="detail.sales_status" disabled /></el-form-item>
        <el-form-item label="编码冻结"><el-input :model-value="detail.is_code_frozen ? '已冻结' : '未冻结'" disabled /></el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>图片占位</template>
      <el-empty description="图片资料占位，不上传真实附件" />
    </el-card>

    <el-card shadow="never">
      <template #header>SKU资料</template>
      <el-table :data="relatedSkus" border empty-text="暂无SKU数据">
        <el-table-column prop="sku_code" label="SKU" min-width="150" />
        <el-table-column prop="size" label="尺码" min-width="100" />
        <el-table-column prop="material" label="材质" min-width="130" />
        <el-table-column label="卖点" min-width="180">
          <template #default="{ row }">{{ formatList(row.selling_points) }}</template>
        </el-table-column>
        <el-table-column prop="package_weight" label="箱规重量" min-width="120" />
        <el-table-column prop="package_volume" label="箱规体积" min-width="120" />
        <el-table-column label="编码冻结" min-width="100">
          <template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <div class="product-actions">
      <el-button disabled>保存占位</el-button>
      <el-button type="primary" :loading="freezing" :disabled="loading || !detail.id || detail.is_code_frozen" @click="handleFreezeCode">
        编码冻结
      </el-button>
    </div>

    <el-empty v-if="!loading && !errorMessage && !detail.id" description="暂无商品主数据详情" />
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchProductMasterDetail, fetchProductSkuList, freezeProductCode } from '../../api/products';

const route = useRoute();
const detail = ref({});
const skus = ref([]);
const loading = ref(false);
const freezing = ref(false);
const errorMessage = ref('');
const warningMessage = ref('');
const dataStatus = ref('loading');

const statusTagType = computed(() => {
  if (dataStatus.value === 'mock') return 'info';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'error') return 'danger';
  return 'success';
});

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
  if (Array.isArray(value)) return value.join(', ');
  return value || '-';
}

async function loadProductDetail() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const [detailResponse, skuResponse] = await Promise.all([
      fetchProductMasterDetail(route.params.id || 1),
      fetchProductSkuList()
    ]);
    if (!detailResponse.success) throw new Error(detailResponse.message || '商品主数据详情接口返回失败');
    if (!skuResponse.success) throw new Error(skuResponse.message || '商品SKU接口返回失败');

    detail.value = getDetail(detailResponse.data);
    skus.value = getRows(skuResponse.data);
    dataStatus.value = detailResponse.data?.api_status || detailResponse.data?.status || 'api';
    if (detailResponse.data?.api_status === 'fallback' || skuResponse.data?.api_status === 'fallback') {
      warningMessage.value = detailResponse.message || skuResponse.message || '商品主数据接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '商品主数据详情接口请求失败';
    detail.value = {};
    skus.value = [];
  } finally {
    loading.value = false;
  }
}

async function handleFreezeCode() {
  freezing.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await freezeProductCode(detail.value.id);
    if (!response.success) {
      throw new Error(response.message || '编码冻结接口返回失败');
    }

    detail.value = {
      ...detail.value,
      ...getDetail(response.data),
      is_code_frozen: true
    };
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '编码冻结接口失败，已显示Mock fallback结果';
    }
    ElMessage.success('编码冻结请求已完成');
  } catch (error) {
    errorMessage.value = error?.message || '编码冻结接口请求失败';
    ElMessage.error(errorMessage.value);
  } finally {
    freezing.value = false;
  }
}

onMounted(loadProductDetail);
</script>

<style scoped>
.product-page {
  display: grid;
  gap: 16px;
}

.product-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.product-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
