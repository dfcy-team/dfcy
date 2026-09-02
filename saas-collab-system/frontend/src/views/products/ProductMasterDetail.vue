<template>
  <section class="detail-page">
    <header class="page-header"><div><p class="eyebrow">UI-P5 · 商品主数据</p><h1 class="page-title">商品详情</h1><p>编码冻结是独立授权动作，不改变商品生命周期或销售状态。</p></div><el-tag :type="stateTagType(state)">{{ state }}</el-tag></header>
    <el-alert v-if="message" :title="message" :type="state==='error'?'error':'warning'" show-icon :closable="false"/>
    <el-card v-loading="loading" shadow="never"><template #header>基础属性</template><el-descriptions :column="2" border><el-descriptions-item label="SPU">{{detail.spu_code||'-'}}</el-descriptions-item><el-descriptions-item label="商品名称">{{detail.product_name||'-'}}</el-descriptions-item><el-descriptions-item label="类目">{{detail.category||'-'}}</el-descriptions-item><el-descriptions-item label="生命周期">{{detail.lifecycle_status||'-'}}</el-descriptions-item><el-descriptions-item label="销售状态">{{detail.sales_status||'-'}}</el-descriptions-item><el-descriptions-item label="编码状态">{{detail.is_code_frozen?'已冻结':'未冻结'}}</el-descriptions-item></el-descriptions></el-card>
    <el-card shadow="never"><template #header>授权范围内的 SKU</template><el-table :data="relatedSkus" border empty-text="暂无可见 SKU"><el-table-column prop="sku_code" label="SKU" min-width="150"/><el-table-column prop="size" label="尺码"/><el-table-column prop="material" label="材质"/><el-table-column prop="package_weight" label="重量"/><el-table-column label="编码冻结"><template #default="{row}">{{row.is_code_frozen?'是':'否'}}</template></el-table-column></el-table></el-card>
    <div class="actions"><el-button v-if="canManage" type="primary" :disabled="loading||!detail.id||detail.is_code_frozen" @click="openGenerateSku">生成SKU编码</el-button><el-button v-if="canFreeze" type="primary" :disabled="loading||!detail.id||detail.is_code_frozen" :loading="freezing" @click="handleFreeze">冻结编码</el-button><el-alert v-if="!canManage&&!canFreeze" title="当前角色没有商品主数据管理权限，仅可查看。" type="info" :closable="false"/></div>
    <el-dialog v-model="skuDialog" title="生成 SKU 编码" width="min(560px, 94vw)" destroy-on-close :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="颜色" required>
          <el-select v-model="skuForm.color_code" filterable placeholder="请选择颜色" style="width:100%">
            <el-option v-for="color in activeColors" :key="color.id || color.code" :label="`${color.name} (${color.code})`" :value="color.code" />
          </el-select>
        </el-form-item>
        <el-form-item v-for="dimension in specDimensions" :key="dimension.code" :label="`${dimension.name}（${dimension.code}）`" required>
          <el-select v-if="Array.isArray(dimension.values) && dimension.values.length" v-model="skuForm.spec_values[dimension.code]" filterable allow-create default-first-option style="width:100%">
            <el-option v-for="value in dimension.values" :key="value" :label="value" :value="value" />
          </el-select>
          <el-input v-else v-model="skuForm.spec_values[dimension.code]" :placeholder="`请输入${dimension.name}`" />
        </el-form-item>
        <el-alert v-if="!specDimensions.length" title="当前末级分类尚未配置 SKU 规格维度，请先在属性设置中配置。" type="warning" :closable="false" />
      </el-form>
      <template #footer><el-button @click="skuDialog=false">取消</el-button><el-button type="primary" :loading="skuSaving" @click="handleGenerateSku">生成</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { createProductSku, fetchProductCategories, fetchProductColors, fetchProductMasterDetail, fetchProductSkuList, freezeProductCode } from '../../api/products';
import { apiState, collectionRows, detailData, stateTagType } from '../../utils/businessResponse';

const route = useRoute();
const auth = useAuthStore();
const detail = ref({});
const skus = ref([]);
const categories = ref([]);
const colors = ref([]);
const loading = ref(false);
const freezing = ref(false);
const skuSaving = ref(false);
const skuDialog = ref(false);
const state = ref('loading');
const message = ref('');
const skuForm = reactive({ color_code: '', spec_values: {} });
const canManage = computed(() => auth.hasPermission('products.master.manage'));
const canFreeze = computed(() => auth.hasPermission('products.master.freeze'));
const relatedSkus = computed(() => skus.value.filter((sku) => sku.spu === detail.value.id));
const categoryNodeId = computed(() => {
  const category = detail.value.category_node;
  return category && typeof category === 'object' ? category.id : category;
});
const selectedCategory = computed(() => {
  const embedded = detail.value.category_node;
  return categories.value.find((category) => category.id === categoryNodeId.value)
    || (embedded && typeof embedded === 'object' ? embedded : null);
});
const specDimensions = computed(() => selectedCategory.value?.spec_dimensions || []);
const activeColors = computed(() => colors.value.filter((color) => color.is_active !== false));

async function load() {
  loading.value = true;
  message.value = '';
  const id = route.params.id || 1;
  const [d, s, categoryResponse, colorResponse] = await Promise.all([
    fetchProductMasterDetail(id),
    fetchProductSkuList({ spu_id: id, page: 1, page_size: 100 }),
    fetchProductCategories(),
    fetchProductColors()
  ]);
  if (categoryResponse.success) categories.value = collectionRows(categoryResponse.data);
  if (colorResponse.success) colors.value = collectionRows(colorResponse.data);
  if (d.success && s.success) {
    detail.value = detailData(d.data);
    skus.value = collectionRows(s.data);
    state.value = apiState(d.data);
  } else {
    state.value = 'error';
    message.value = d.message || s.message;
  }
  loading.value = false;
}

function openGenerateSku() {
  skuForm.color_code = '';
  skuForm.spec_values = Object.fromEntries(specDimensions.value.map((dimension) => [dimension.code, '']));
  skuDialog.value = true;
}

async function handleGenerateSku() {
  if (!skuForm.color_code) return ElMessage.warning('请选择颜色');
  if (!specDimensions.value.length) return ElMessage.warning('当前分类未配置 SKU 规格，无法生成编码');
  if (specDimensions.value.some((dimension) => !String(skuForm.spec_values[dimension.code] || '').trim())) {
    return ElMessage.warning('请完整填写 SKU 规格');
  }
  skuSaving.value = true;
  const response = await createProductSku({
    spu: detail.value.id,
    color_code: skuForm.color_code,
    spec_values: skuForm.spec_values
  });
  if (response.success) {
    skuDialog.value = false;
    ElMessage.success(`SKU ${detailData(response.data).sku_code || ''} 已生成`);
    await load();
  } else {
    state.value = 'error';
    message.value = response.message || 'SKU 生成失败';
  }
  skuSaving.value = false;
}

async function handleFreeze() {
  freezing.value = true;
  const response = await freezeProductCode(detail.value.id);
  if (response.success) {
    detail.value = { ...detail.value, ...detailData(response.data) };
    state.value = apiState(response.data);
  } else {
    state.value = 'error';
    message.value = response.message;
  }
  freezing.value = false;
}

onMounted(load);
</script>
<style scoped>.detail-page{display:grid;gap:16px}.page-header{display:flex;justify-content:space-between;gap:16px}.page-header p{margin:4px 0 0;color:#64748b}.eyebrow{font-size:12px;font-weight:700;color:#0f766e!important}.actions{display:flex;align-items:center;gap:12px}</style>
