<template>
  <section class="business-page">
    <header class="page-head">
      <div>
        <h1>商品明细数据</h1>
        <p>查看旧商品与新编码的对应关系，导入旧商品后可逐条调整并生成新 SPU/SKU。</p>
      </div>
      <div class="header-actions">
        <el-button @click="downloadTemplate">下载导入模板</el-button>
        <el-button v-if="canManage" type="primary" @click="$refs.file?.click()">导入旧商品</el-button>
        <input ref="file" hidden type="file" accept=".csv,text/csv" @change="importFile" />
      </div>
    </header>

    <el-form class="filters" inline @submit.prevent="search">
      <el-form-item label="全局搜索">
        <el-input
          v-model="filters.search"
          clearable
          placeholder="旧/新 SPU、SKU、商品名称、分类、颜色或规格"
          @keyup.enter="search"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="message"
      :title="message"
      :type="messageType"
      show-icon
      closable
      @close="message = ''"
    />

    <el-table
      v-loading="loading"
      :data="rows"
      border
      stripe
      empty-text="暂无商品明细数据"
      style="margin-top: 16px"
    >
      <el-table-column prop="legacy_spu_code" label="旧 SPU 编码" min-width="130" show-overflow-tooltip />
      <el-table-column prop="legacy_sku_code" label="旧 SKU 编码" min-width="150" show-overflow-tooltip />
      <el-table-column prop="spu_code" label="新 SPU 编码" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ row.spu_code || '-' }}</template>
      </el-table-column>
      <el-table-column prop="sku_code" label="新 SKU 编码" min-width="210" show-overflow-tooltip>
        <template #default="{ row }">{{ row.sku_code || '-' }}</template>
      </el-table-column>
      <el-table-column prop="product_name" label="商品名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="category_name" label="分类" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.category_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="color_code" label="颜色" min-width="100" show-overflow-tooltip>
        <template #default="{ row }">{{ row.color_code || '-' }}</template>
      </el-table-column>
      <el-table-column prop="specification" label="规格" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ row.specification || '-' }}</template>
      </el-table-column>
      <el-table-column prop="purchase_price" label="采购价格" min-width="110" align="right">
        <template #default="{ row }">{{ formatPrice(row.purchase_price) }}</template>
      </el-table-column>
      <el-table-column prop="status_name" label="状态" width="100" />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.row_type === 'legacy' && row.status !== 'generated' && canManage"
            link
            type="primary"
            @click="edit(row)"
          >
            调整并生成
          </el-button>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
    </el-table>

    <footer class="pager">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        @current-change="load"
        @size-change="changePageSize"
      />
    </footer>

    <el-dialog v-model="visible" title="调整旧商品并生成新编码" width="600px">
      <el-form label-position="top">
        <el-form-item label="商品名称" required><el-input v-model="form.product_name" /></el-form-item>
        <el-form-item label="末级分类" required>
          <el-select v-model="form.category_node" filterable clearable style="width: 100%">
            <el-option v-for="item in leaves" :key="item.id" :label="`${item.code} ${item.name}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="属性码（选填，未填自动补 0）">
          <el-select v-model="form.attribute_code" clearable style="width: 100%">
            <el-option v-for="item in attributes" :key="item.id" :label="`${item.code} ${item.name}`" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色" required>
          <el-select v-model="form.color_code" filterable clearable style="width: 100%">
            <el-option
              v-for="item in colors.filter((value) => value.is_active !== false)"
              :key="item.id"
              :label="`${item.code} ${item.name}`"
              :value="item.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="规格">
          <el-select v-if="specOptions.length" v-model="form.specification" filterable allow-create style="width: 100%">
            <el-option v-for="value in specOptions" :key="value" :label="value" :value="value" />
          </el-select>
          <el-input v-else v-model="form.specification" placeholder="例如 150cm×220cm" />
        </el-form-item>
        <el-form-item label="采购价格">
          <el-input v-model="form.purchase_price" placeholder="例如 12.50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveGenerate">生成新编码</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useAuthStore } from '../../stores/auth';
import {
  fetchProductCategories,
  fetchProductColors,
  fetchProductAttributes,
  fetchProductDetailList,
  importLegacyProductItems,
  updateLegacyProductItem,
  generateLegacyProductItem,
} from '../../api/products';
import { collectionRows, collectionTotal } from '../../utils/businessResponse';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.master.manage'));
const filters = reactive({ search: '' });
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const message = ref('');
const messageType = ref('success');
const categories = ref([]);
const colors = ref([]);
const attributes = ref([]);
const visible = ref(false);
const form = reactive({
  id: null,
  product_name: '',
  category_node: null,
  attribute_code: '',
  color_code: '',
  specification: '',
  purchase_price: '',
});

const leaves = computed(() => categories.value.filter((item) => Number(item.level) === 3 && item.is_active !== false));
const selectedCategory = computed(() => categories.value.find((item) => item.id === form.category_node));
const specOptions = computed(() => selectedCategory.value?.spec_dimensions?.[0]?.values || []);

function show(value, type = 'success') {
  message.value = value;
  messageType.value = type;
}

function formatPrice(value) {
  if (value === null || value === undefined || value === '') return '-';
  return Number.isFinite(Number(value)) ? Number(value).toFixed(4) : value;
}

async function load() {
  loading.value = true;
  const response = await fetchProductDetailList({
    search: filters.search.trim() || undefined,
    page: page.value,
    page_size: pageSize.value,
  });
  if (response.success) {
    rows.value = collectionRows(response.data);
    total.value = collectionTotal(response.data);
  } else {
    rows.value = [];
    total.value = 0;
    show(response.message || '商品明细加载失败', 'error');
  }
  loading.value = false;
}

async function loadDictionaries() {
  const [categoryResponse, colorResponse, attributeResponse] = await Promise.all([
    fetchProductCategories(),
    fetchProductColors(),
    fetchProductAttributes(),
  ]);
  if (categoryResponse.success) categories.value = collectionRows(categoryResponse.data);
  if (colorResponse.success) colors.value = collectionRows(colorResponse.data);
  if (attributeResponse.success) attributes.value = collectionRows(attributeResponse.data);
}

function search() {
  page.value = 1;
  load();
}

function reset() {
  filters.search = '';
  search();
}

function changePageSize() {
  page.value = 1;
  load();
}

function edit(row) {
  Object.assign(form, {
    id: row.id,
    product_name: row.product_name || '',
    category_node: row.category_node || null,
    attribute_code: row.attribute_code === '0' ? '' : row.attribute_code || '',
    color_code: row.color_code || '',
    specification: row.specification || '',
    purchase_price: row.purchase_price ?? '',
  });
  visible.value = true;
}

async function saveGenerate() {
  if (!form.product_name.trim() || !form.category_node || !form.color_code) {
    show('请填写商品名称并选择末级分类和颜色', 'warning');
    return;
  }
  saving.value = true;
  const updateResponse = await updateLegacyProductItem(form.id, {
    product_name: form.product_name.trim(),
    category_node: form.category_node,
    attribute_code: form.attribute_code || '0',
    color_code: form.color_code,
    specification: form.specification || '0',
    purchase_price: form.purchase_price === '' ? null : form.purchase_price,
  });
  if (!updateResponse.success) {
    show(updateResponse.message || '保存失败', 'error');
    saving.value = false;
    return;
  }
  const generateResponse = await generateLegacyProductItem(form.id);
  saving.value = false;
  if (!generateResponse.success) {
    show(generateResponse.message || '生成失败', 'error');
    return;
  }
  visible.value = false;
  show('新 SPU/SKU 编码已生成');
  await load();
}

async function importFile(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!/\.csv$/i.test(file.name)) {
    show('请选择 CSV 文件', 'warning');
    return;
  }
  const response = await importLegacyProductItems(await file.text());
  if (!response.success) {
    show(response.message || '导入失败', 'error');
    return;
  }
  const result = response.data || {};
  show(`已导入 ${result.created || 0} 条，更新 ${result.updated || 0} 条；请逐条调整并生成新编码`);
  await load();
}

function downloadTemplate() {
  const csv = '\ufeff旧SPU编码,旧SKU编码,商品名称,分类编码,属性码,颜色编码,规格,采购价格\nOLD-SPU-001,OLD-SKU-001,示例商品,,,,,12.50\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '旧商品导入模板.csv';
  anchor.click();
  URL.revokeObjectURL(url);
}

onMounted(() => {
  loadDictionaries();
  load();
});
</script>

<style scoped>
.business-page { display: grid; gap: 16px; }
.page-head, .pager { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head h1 { margin: 0 0 8px; }
.page-head p { margin: 0; color: #64748b; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.filters { padding: 12px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.pager { color: #64748b; font-size: 13px; margin-top: 12px; }
.muted { color: #94a3b8; }
@media (max-width: 800px) {
  .page-head, .pager { align-items: flex-start; flex-direction: column; }
  .header-actions { width: 100%; }
}
</style>
