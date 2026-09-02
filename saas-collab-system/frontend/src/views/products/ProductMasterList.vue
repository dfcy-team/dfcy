<template>
  <section class="business-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">UI-P5 · 商品主数据</p>
        <h1 class="page-title">商品主数据</h1>
        <p>SPU 与 SKU 均由后端按租户和 data_scope 裁剪。</p>
      </div>
      <div class="header-actions">
        <el-tag :type="stateTagType(state)">{{ state }}</el-tag>
        <el-button v-if="canManage" type="primary" @click="openCreate">创建商品</el-button>
      </div>
    </header>

    <div class="content-layout">
      <aside class="category-panel">
        <div class="panel-title">分类目录</div>
        <el-input
          v-model="categoryFilter"
          class="category-search"
          clearable
          placeholder="筛选分类"
          aria-label="筛选分类"
        />
        <el-tree
          :data="filteredCategoryTree"
          node-key="id"
          highlight-current
          default-expand-all
          :expand-on-click-node="false"
          @node-click="selectCategory"
        />
        <el-empty v-if="!categories.length" description="暂无分类目录" :image-size="55" />
      </aside>

      <main class="list-panel">
        <el-form class="filters" @submit.prevent="search">
          <el-form-item class="filter-search" label="名称/SPU">
            <el-input
              v-model="filters.search"
              class="filter-control"
              clearable
              placeholder="输入 SPU 编码或商品名称"
              @keyup.enter="search"
            />
          </el-form-item>
          <el-form-item class="filter-status" label="销售状态">
            <el-select v-model="filters.sales_status" class="filter-control" clearable>
              <el-option label="未上架" value="not_listed" />
              <el-option label="销售中" value="on_sale" />
              <el-option label="暂停" value="paused" />
              <el-option label="停止" value="stopped" />
            </el-select>
          </el-form-item>
          <el-form-item class="filter-actions">
            <el-button type="primary" @click="search">查询</el-button>
            <el-button @click="reset">重置</el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="message"
          :title="message"
          :type="state === 'error' ? 'error' : 'warning'"
          show-icon
          :closable="false"
        />

        <el-table v-loading="loading" :data="rows" border empty-text="当前范围暂无商品主数据">
          <el-table-column prop="spu_code" label="SPU" min-width="150" />
          <el-table-column label="SKU" min-width="220">
            <template #default="{ row }">
              <el-popover
                v-if="skuCodes(row).length"
                :visible="skuPopoverId === row.id"
                class="sku-popover-trigger"
                popper-class="sku-popover"
                placement="bottom-start"
                :width="340"
                trigger="manual"
                :teleported="true"
                @hide="handleSkuPopoverHide(row.id)"
              >
                <template #reference>
                  <button
                    type="button"
                    class="sku-summary"
                    :aria-expanded="skuPopoverId === row.id"
                    :aria-label="`查看 ${skuCount(row)} 个 SKU`"
                    @click.stop="toggleSkuPopover(row.id)"
                    @keydown.esc.stop="closeSkuPopover"
                  >
                    <span>{{ skuPreview(row) }}</span>
                    <span v-if="skuCodes(row).length > skuPreviewLimit" class="sku-more">
                      +{{ skuCodes(row).length - skuPreviewLimit }}
                    </span>
                    <span class="sku-count">({{ skuCount(row) }})</span>
                  </button>
                </template>
                <div class="sku-details" @click.stop>
                  <div class="sku-details-title">SKU 明细（{{ skuCount(row) }}）</div>
                  <ul class="sku-details-list">
                    <li v-for="code in skuCodes(row)" :key="code">{{ code }}</li>
                  </ul>
                </div>
              </el-popover>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="product_name" label="SPU商品名称" min-width="200" />
          <el-table-column label="分类" min-width="150">
            <template #default="{ row }">{{ row.category_name || row.category || '-' }}</template>
          </el-table-column>
          <el-table-column label="生命周期" min-width="120">
            <template #default="{ row }">{{ lifecycleLabel(row.lifecycle_status) }}</template>
          </el-table-column>
          <el-table-column label="销售状态" min-width="110">
            <template #default="{ row }">{{ salesLabel(row.sales_status) }}</template>
          </el-table-column>
          <el-table-column label="编码冻结" min-width="100">
            <template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <router-link :to="`/products/master/${row.id}`">查看</router-link>
            </template>
          </el-table-column>
        </el-table>

        <footer class="pager">
          <span class="pager-summary">共 {{ total }} 条</span>
          <el-pagination
            :current-page="page"
            :page-size="pageSize"
            :page-sizes="pageSizes"
            :pager-count="7"
            layout="sizes, prev, pager, next, jumper"
            :total="total"
            @current-change="changePage"
            @size-change="changePageSize"
          />
        </footer>
      </main>
    </div>

    <el-dialog v-model="createVisible" title="创建商品" width="560px">
      <el-form label-position="top">
        <el-form-item label="商品名称" required>
          <el-input v-model="createForm.product_name" maxlength="200" />
        </el-form-item>
        <el-form-item label="末级分类" required>
          <el-select
            v-model="createForm.category_node"
            filterable
            clearable
            placeholder="请选择 L3 分类"
          >
            <el-option
              v-for="item in leafCategories"
              :key="item.id"
              :label="categoryLabel(item)"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="季节编码">
          <el-select v-model="createForm.season_code">
            <el-option
              v-for="item in seasons"
              :key="item.code"
              :label="`${item.code} · ${item.name}`"
              :value="item.code"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCreate">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import {
  createProductSpu,
  fetchCodingOptions,
  fetchProductCategories,
  fetchProductMasterList
} from '../../api/products';
import {
  apiState,
  collectionRows,
  collectionTotal,
  detailData,
  stateTagType
} from '../../utils/businessResponse';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.master.manage'));
const filters = reactive({ search: '', sales_status: '' });
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const pageSizes = [10, 20, 50, 100];
const loading = ref(false);
const state = ref('loading');
const message = ref('');
const categories = ref([]);
const categoryFilter = ref('');
const selectedCategory = ref(null);
const seasons = ref([]);
const createVisible = ref(false);
const saving = ref(false);
const createForm = reactive({ product_name: '', category_node: null, season_code: '1' });
const skuPopoverId = ref(null);
const skuPreviewLimit = 2;

function categoryLabel(item) {
  return `L${item.level} ${item.code} ${item.name}`;
}

function buildTree(items, parent = null) {
  return items
    .filter((item) => (item.parent ?? item.parent_id ?? null) === parent)
    .map((item) => ({
      ...item,
      label: categoryLabel(item),
      children: buildTree(items, item.id)
    }));
}

const leafCategories = computed(() =>
  categories.value.filter((item) => Number(item.level) === 3 && item.is_active !== false)
);

const filteredCategoryTree = computed(() => {
  const source = buildTree(categories.value);
  const text = categoryFilter.value.trim().toLowerCase();
  if (!text) return [{ id: null, label: '全部分类', children: source }];

  const match = (nodes) =>
    nodes.filter((node) => {
      const children = match(node.children || []);
      return node.label.toLowerCase().includes(text) || children.length
        ? Object.assign(node, { children })
        : false;
    });

  return [{ id: null, label: '全部分类', children: match(source) }];
});

function normalizeSkuCodes(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map((code) => String(code));
  if (typeof value === 'string') return value.split(/[、,\s]+/).filter(Boolean);
  return [];
}

function skuCodes(row) {
  return normalizeSkuCodes(row?.sku_codes);
}

function skuCount(row) {
  const count = Number(row?.sku_count);
  return Number.isFinite(count) && count >= 0 ? count : skuCodes(row).length;
}

function skuPreview(row) {
  return skuCodes(row).slice(0, skuPreviewLimit).join('、');
}

function toggleSkuPopover(id) {
  skuPopoverId.value = skuPopoverId.value === id ? null : id;
}

function closeSkuPopover() {
  skuPopoverId.value = null;
}

function handleSkuPopoverHide(id) {
  if (skuPopoverId.value === id) skuPopoverId.value = null;
}

function handleDocumentClick(event) {
  if (!skuPopoverId.value) return;
  const target = event.target;
  if (target instanceof Element && (target.closest('.sku-summary') || target.closest('.sku-popover'))) return;
  closeSkuPopover();
}

async function loadCategories() {
  const response = await fetchProductCategories();
  if (response.success) categories.value = collectionRows(response.data);
}

async function load() {
  loading.value = true;
  message.value = '';
  closeSkuPopover();
  const params = { ...filters, page: page.value, page_size: pageSize.value };
  if (selectedCategory.value) params.category_node = selectedCategory.value;

  const spus = await fetchProductMasterList(params);
  if (spus.success) {
    rows.value = collectionRows(spus.data).map((spu) => {
      const codes = Array.isArray(spu.sku_codes)
        ? spu.sku_codes.filter(Boolean).map((code) => String(code))
        : normalizeSkuCodes(spu.sku_codes);
      return {
        ...spu,
        sku_codes: codes,
        sku_count: Number.isFinite(Number(spu.sku_count)) ? Number(spu.sku_count) : codes.length
      };
    });
    total.value = collectionTotal(spus.data);
    state.value = apiState(spus.data);
  } else {
    rows.value = [];
    total.value = 0;
    state.value = 'error';
    message.value = spus.message;
  }
  loading.value = false;
}

function search() {
  page.value = 1;
  return load();
}

function reset() {
  filters.search = '';
  filters.sales_status = '';
  selectedCategory.value = null;
  return search();
}

function selectCategory(node) {
  selectedCategory.value = node?.id || null;
  return search();
}

function changePage(nextPage) {
  if (nextPage === page.value) return;
  page.value = nextPage;
  return load();
}

function changePageSize(nextPageSize) {
  if (nextPageSize === pageSize.value && page.value === 1) return;
  pageSize.value = nextPageSize;
  page.value = 1;
  return load();
}

function lifecycleLabel(value) {
  return { draft: '草稿', active: '启用', discontinued: '已停用' }[value] || value || '-';
}

function salesLabel(value) {
  return { not_listed: '未上架', on_sale: '销售中', paused: '暂停', stopped: '停止' }[value] || value || '-';
}

async function openCreate() {
  if (!seasons.value.length) {
    const response = await fetchCodingOptions();
    if (response.success) seasons.value = detailData(response.data)?.seasons || [];
  }
  Object.assign(createForm, {
    product_name: '',
    category_node: null,
    season_code: seasons.value[0]?.code || '1'
  });
  createVisible.value = true;
}

async function saveCreate() {
  if (!createForm.product_name.trim() || !createForm.category_node) {
    return ElMessage.warning('请填写商品名称并选择末级分类');
  }
  saving.value = true;
  const response = await createProductSpu({
    product_name: createForm.product_name.trim(),
    category_node: createForm.category_node,
    season_code: createForm.season_code || '1'
  });
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '商品创建失败');
  createVisible.value = false;
  ElMessage.success('商品已创建');
  return load();
}

onMounted(async () => {
  document.addEventListener('click', handleDocumentClick, true);
  await Promise.all([loadCategories(), load()]);
  const response = await fetchCodingOptions();
  if (response.success) seasons.value = detailData(response.data)?.seasons || [];
});

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick, true);
});
</script>

<style scoped>
.business-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.page-header,
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.page-header p {
  margin: 4px 0 0;
  color: #64748b;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  color: #0f766e !important;
}

.content-layout {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  align-items: start;
  gap: 16px;
  min-width: 0;
}

.category-panel,
.list-panel {
  min-width: 0;
  padding: 14px;
  background: #fff;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
}

.panel-title {
  margin-bottom: 10px;
  font-weight: 700;
}

.category-search {
  margin-bottom: 10px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.filters :deep(.el-form-item) {
  margin: 0;
}

.filter-search {
  flex: 1 1 280px;
  min-width: 220px;
}

.filter-status {
  flex: 0 1 180px;
  min-width: 160px;
}

.filter-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.filter-control {
  width: 100%;
}

.filter-actions :deep(.el-form-item__content) {
  gap: 8px;
}

.sku-summary {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 4px;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.sku-summary > span:first-child {
  max-width: 155px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sku-summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.sku-more,
.sku-count {
  flex-shrink: 0;
  color: #64748b;
  font-size: 12px;
}

.muted {
  color: #94a3b8;
}

.pager {
  flex-wrap: wrap;
  margin-top: 12px;
  color: #64748b;
  font-size: 13px;
}

.pager-summary {
  flex-shrink: 0;
  white-space: nowrap;
}

.pager :deep(.el-pagination) {
  margin-left: auto;
}

:global(.sku-popover) {
  max-width: min(340px, calc(100vw - 32px));
}

:global(.sku-popover .sku-details) {
  max-height: 220px;
  overflow-x: hidden;
  overflow-y: auto;
  white-space: normal;
  word-break: break-all;
}

.sku-details-title {
  margin-bottom: 8px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.sku-details-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
  color: #475569;
}

@media (max-width: 960px) {
  .content-layout {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .filter-search {
    flex-basis: 220px;
  }
}

@media (max-width: 800px) {
  .content-layout {
    grid-template-columns: 1fr;
  }

  .category-panel {
    max-height: 320px;
    overflow: auto;
  }
}

@media (max-width: 620px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .filters {
    align-items: stretch;
    flex-direction: column;
  }

  .filter-search,
  .filter-status,
  .filter-actions {
    width: 100%;
    min-width: 0;
  }

  .filter-actions :deep(.el-button) {
    flex: 1;
  }

  .pager {
    align-items: flex-start;
    flex-direction: column;
  }

  .pager :deep(.el-pagination) {
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
