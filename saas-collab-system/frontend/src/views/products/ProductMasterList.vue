<template>
  <section class="business-page">
    <header class="page-header">
      <div class="header-copy">
        <p class="eyebrow">商品资料与编码</p>
        <h1 class="page-title">商品主数据</h1>
        <p class="page-subtitle">维护商品基本信息、分类归属和 SPU / SKU 编码。</p>
        <details class="coding-guide">
          <summary>商品 SKU 生成规则说明</summary>
          <div class="coding-guide-content">
            <p>
              新建商品时，系统根据所选分类和一位季节码生成 SPU；季节码未填写时按
              <code>0</code> 处理，同一分类和季节码组合内按 <code>001–999</code> 顺序编号。
            </p>
            <p>
              新增 SKU 时，编码格式为 <code>SPU编码-颜色编码[-规格值]</code>。颜色需选择启用的颜色字典；多个规格值按类目配置顺序以
              <code>×</code> 连接，没有规格值时省略最后一段。
            </p>
            <p class="coding-guide-note">SKU 编码生成后，所关联的 SPU、颜色和规格不能直接修改，如需调整请先确认商品业务影响。</p>
          </div>
        </details>
      </div>
      <div class="header-actions">
        <el-tag :type="stateTagType(state)">{{ stateLabel }}</el-tag>
        <el-button
          v-if="canManage"
          :disabled="!selectedMasterRows.length"
          @click="openBulkMasterEdit"
        >
          批量修改
        </el-button>
        <el-button
          v-if="canManage"
          :disabled="!selectedMasterRows.length"
          @click="openMoveCategory"
        >
          移动目录
        </el-button>
        <el-button v-if="canManage" type="primary" @click="openCreate">创建商品</el-button>
      </div>
    </header>

    <div class="workspace">
      <aside class="category-panel">
        <div class="panel-title">
          <strong>分类目录</strong>
          <el-button link @click="selectCategory(null)">全部</el-button>
        </div>
        <el-input v-model="categoryFilter" clearable placeholder="搜索分类" />
        <el-tree
          ref="categoryTreeRef"
          :data="categoryTree"
          node-key="id"
          :props="{ label: 'displayName', children: 'children' }"
          :filter-node-method="filterCategory"
          :expand-on-click-node="false"
          default-expand-all
          highlight-current
          @node-click="selectCategory"
        />
      </aside>

      <main class="content-panel">
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
              <el-option label="未刊登" value="not_listed" />
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

        <el-table
          v-loading="loading"
          :data="rows"
          row-key="id"
          border
          class="product-master-table"
          :row-class-name="productRowClassName"
          :row-style="productRowStyle"
          empty-text="当前范围暂无商品主数据"
          @selection-change="selectedMasterRows = $event"
        >
          <el-table-column type="index" label="序号" width="70" :index="(page - 1) * pageSize + 1" />
          <el-table-column v-if="canManage" type="selection" width="48" reserve-selection />
          <el-table-column prop="spu_code" label="SPU" min-width="150">
            <template #default="{ row }">
              <SpuCodeDisplay :code="row.spu_code" />
            </template>
          </el-table-column>
          <el-table-column label="SKU" min-width="220">
            <template #default="{ row }">
              <el-popover
                v-if="skuCodes(row).length"
                :visible="skuPopoverId === row.id"
                placement="bottom-start"
                trigger="manual"
                :width="360"
                popper-class="sku-popover"
                @hide="handleSkuPopoverHide(row.id)"
              >
                <template #reference>
                  <button
                    type="button"
                    class="sku-summary"
                    aria-haspopup="dialog"
                    :aria-label="`查看 ${skuCount(row)} 个 SKU`"
                    @click.stop="toggleSkuPopover(row)"
                  >
                    <span>{{ skuPreview(row) }}</span>
                    <span v-if="skuCodes(row).length > skuPreviewLimit" class="sku-more">
                      +{{ skuCodes(row).length - skuPreviewLimit }}
                    </span>
                    <span class="sku-count">({{ skuCount(row) }})</span>
                  </button>
                </template>
                <div class="sku-details">
                  <div v-if="selectedSkuTitle" class="sku-details-subtitle">{{ selectedSkuTitle }}</div>
                  <div class="sku-details-title">共 {{ skuCodes(row).length }} 个 SKU</div>
                  <div class="sku-details-list">
                    <div v-for="code in skuCodes(row)" :key="code" class="sku-detail-row">
                      <code class="sku-detail-code">{{ code }}</code>
                      <el-button link type="primary" @click="copySku(code)">复制</el-button>
                    </div>
                  </div>
                </div>
              </el-popover>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="product_name" label="SPU商品名称" min-width="200" />
          <el-table-column prop="category" label="类目" min-width="120" />
          <el-table-column label="生命周期" min-width="120">
            <template #default="{ row }">{{ productLifecycleStatusLabel(row.lifecycle_status) }}</template>
          </el-table-column>
          <el-table-column label="销售状态" min-width="110">
            <template #default="{ row }">{{ productSalesStatusLabel(row.sales_status) }}</template>
          </el-table-column>
          <el-table-column label="编码冻结" min-width="100">
            <template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="220" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <router-link :to="`/products/master/${row.id}`">查看</router-link>
                <el-button
                  v-if="canManage"
                  link
                  type="primary"
                  :disabled="!row.id"
                  @click="openEdit(row)"
                >
                  编辑
                </el-button>
                <el-button
                  v-if="canManage"
                  link
                  type="primary"
                  :disabled="!row.id"
                  @click="openSkuCreate(row)"
                >
                  生成 SKU
                </el-button>
              </div>
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

    <el-dialog v-model="createOpen" title="创建商品" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="商品名称" required>
          <el-input v-model="createForm.product_name" />
        </el-form-item>
        <el-form-item label="末级分类" required>
          <el-tree-select
            v-model="createForm.category_node"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'name', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
          />
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="createForm.brand" />
        </el-form-item>
        <el-form-item label="季节编码">
          <el-input v-model="createForm.season_code" placeholder="例如 0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProduct">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editOpen" title="编辑商品主数据" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="商品名称" required>
          <el-input v-model="editForm.product_name" maxlength="200" />
        </el-form-item>
        <el-form-item label="末级分类" required>
          <el-tree-select
            v-model="editForm.category_node"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'name', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="skuCreateOpen" title="生成 SKU" width="min(600px, 94vw)">
      <el-alert
        v-if="skuTarget"
        :title="`${skuTarget.spu_code || ''} · ${skuTarget.product_name || ''}`"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="sku-form">
        <el-form-item label="启用颜色" required>
          <el-select
            v-model="skuForm.color_code"
            class="form-control"
            filterable
            clearable
            placeholder="请选择启用的颜色"
          >
            <el-option
              v-for="color in activeColors"
              :key="color.id || color.code"
              :label="`${color.name}（${color.code}）`"
              :value="color.code"
            />
          </el-select>
        </el-form-item>
        <template v-if="skuDimensions.length">
          <el-form-item
            v-for="dimension in skuDimensions"
            :key="dimension.code"
            :label="dimension.name || dimension.code"
          >
            <el-select
              v-if="Array.isArray(dimension.values) && dimension.values.length"
              v-model="skuForm.spec_values[dimension.code]"
              class="form-control"
              filterable
              clearable
              allow-create
              default-first-option
              :placeholder="`请选择或填写${dimension.name || dimension.code}`"
            >
              <el-option
                v-for="value in dimension.values"
                :key="value"
                :label="value"
                :value="value"
              />
            </el-select>
            <el-input
              v-else
              v-model="skuForm.spec_values[dimension.code]"
              class="form-control"
              clearable
              :placeholder="`填写${dimension.name || dimension.code}（可选）`"
            />
          </el-form-item>
        </template>
        <el-empty v-else description="该分类未配置规格，可直接按颜色生成 SKU" :image-size="64" />
      </el-form>
      <template #footer>
        <el-button @click="skuCreateOpen = false">取消</el-button>
        <el-button type="primary" :loading="skuSaving" @click="saveSku">生成 SKU</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bulkMasterVisible" title="批量修改商品信息" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-alert
        :title="`已选择 ${selectedMasterRows.length} 条商品主数据`"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="bulk-master-form">
        <el-form-item label="SPU商品名称">
          <el-input v-model="bulkMasterForm.product_name" clearable placeholder="留空则不修改已选商品名称" />
        </el-form-item>
        <el-form-item label="商品目录">
          <el-tree-select
            v-model="bulkMasterForm.category_node"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'displayName', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
            clearable
            placeholder="留空则不移动目录"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bulkMasterVisible = false">取消</el-button>
        <el-button type="primary" :loading="bulkMasterSaving" @click="saveBulkMasterEdit">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="moveCategoryVisible" title="移动商品目录" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-alert
        :title="`将 ${selectedMasterRows.length} 条商品移动到指定末级目录`"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="bulk-master-form">
        <el-form-item label="目标商品目录" required>
          <el-tree-select
            v-model="moveCategoryNode"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'displayName', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
            placeholder="请选择启用的末级目录"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="moveCategoryVisible = false">取消</el-button>
        <el-button type="primary" :loading="moveCategorySaving" @click="saveMoveCategory">确认移动</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  createProductSku,
  createProductSpu,
  fetchProductCategories,
  fetchProductColors,
  fetchProductMasterList,
  updateProductSpu,
  bulkUpdateProductSpus
} from '../../api/products';
import { useAuthStore } from '../../stores/auth';
import { apiState, collectionRows, collectionTotal, detailData, stateTagType } from '../../utils/businessResponse';
import { productLifecycleStatusLabel, productSalesStatusLabel } from '../../utils/productLabels';
import { buildCategoryTree, categoryRowClass, categoryRowStyle } from '../../utils/productCategoryPresentation';
import SpuCodeDisplay from '../../components/SpuCodeDisplay.vue';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.master.manage'));
const filters = reactive({ search: '', sales_status: '', category_id: '' });
const rows = ref([]);
const categories = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const pageSizes = [10, 20, 50, 100];
const loading = ref(false);
const state = ref('loading');
const message = ref('');
const stateLabels = {
  loading: '加载中',
  connected: '已同步',
  fallback: '备用数据',
  mock: '演示数据',
  pending: '等待响应',
  error: '加载失败'
};
const stateLabel = computed(() => stateLabels[state.value] || '状态未知');
const categorySearch = ref('');
// Keep the established categoryFilter name as the public form contract while
// retaining the descriptive internal alias used by the tree watcher.
const categoryFilter = categorySearch;
const categoryTreeRef = ref(null);
const createOpen = ref(false);
const saving = ref(false);
const createForm = reactive({ product_name: '', category_node: null, brand: '', season_code: '0' });
const editOpen = ref(false);
const editSaving = ref(false);
const editForm = reactive({ id: null, product_name: '', category_node: null });
const colors = ref([]);
const skuCreateOpen = ref(false);
const skuSaving = ref(false);
const skuTarget = ref(null);
const skuForm = reactive({ color_code: '', spec_values: {} });
const skuPreviewLimit = 2;
const skuPopoverId = ref(null);
const selectedSkuTitle = ref('');
const selectedMasterRows = ref([]);
const bulkMasterVisible = ref(false);
const bulkMasterSaving = ref(false);
const bulkMasterForm = reactive({ product_name: '', category_node: null });
const moveCategoryVisible = ref(false);
const moveCategorySaving = ref(false);
const moveCategoryNode = ref(null);

const categoryTree = computed(() => buildCategoryTree(categories.value));
const productRowClassName = ({ row }) => categoryRowClass(row, categories.value);
const productRowStyle = ({ row }) => categoryRowStyle(row, categories.value);

const activeColors = computed(() => colors.value.filter((item) => item?.is_active !== false));
const skuCategory = computed(() => {
  const categoryId = skuTarget.value?.category_node;
  return categories.value.find((item) => String(item.id) === String(categoryId)) || null;
});

function sortSpecValues(values) {
  if (!Array.isArray(values)) return values;
  return values
    .map((value, index) => ({ value, index, hasHyphen: String(value).includes('-') }))
    .sort((left, right) => Number(left.hasHyphen) - Number(right.hasHyphen) || left.index - right.index)
    .map((item) => item.value);
}

const skuDimensions = computed(() => {
  const dimensions = skuCategory.value?.spec_dimensions;
  return Array.isArray(dimensions)
    ? dimensions
        .filter((item) => item && item.code)
        .map((item) => ({ ...item, values: sortSpecValues(item.values) }))
    : [];
});

watch(categorySearch, (value) => categoryTreeRef.value?.filter(value));

function filterCategory(value, data) {
  return (
    !value ||
    String(data.name || '').toLowerCase().includes(value.toLowerCase()) ||
    String(data.code || '').toLowerCase().includes(value.toLowerCase())
  );
}

function categoryDisabled(data) {
  return !isLeafCategory(data);
}

function isLeafCategory(data) {
  if (!data || data.is_active === false || Number(data.level) < 2) return false;
  const hasChildren =
    (Array.isArray(data.children) && data.children.length > 0) ||
    categories.value.some((item) => String(item.parent || '') === String(data.id));
  return !hasChildren;
}

function findCategory(categoryId) {
  return categories.value.find((item) => String(item.id) === String(categoryId)) || null;
}

function isUsableCategory(categoryId) {
  return isLeafCategory(findCategory(categoryId));
}

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

function toggleSkuPopover(row) {
  skuPopoverId.value = skuPopoverId.value === row.id ? null : row.id;
  selectedSkuTitle.value = row.spu_code || row.product_name || '';
}

function handleSkuPopoverHide(rowId) {
  if (skuPopoverId.value === rowId) skuPopoverId.value = null;
}

function handleDocumentClick(event) {
  if (event.target.closest('.sku-popover') || event.target.closest('.sku-summary')) return;
  skuPopoverId.value = null;
}

async function copySku(code) {
  const text = String(code);
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
    await navigator.clipboard.writeText(text);
  } catch {
    const input = document.createElement('textarea');
    input.value = text;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.appendChild(input);
    input.select();
    document.execCommand('copy');
    input.remove();
  }
  ElMessage.success('SKU 已复制');
}

function selectCategory(node) {
  filters.category_id = node?.id || '';
  page.value = 1;
  return load();
}

async function load() {
  loading.value = true;
  message.value = '';
  const spus = await fetchProductMasterList({ ...filters, page: page.value, page_size: pageSize.value });
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

async function loadCategories() {
  const response = await fetchProductCategories({ page: 1, page_size: 500 });
  if (response.success) categories.value = collectionRows(response.data);
}

async function loadColors() {
  if (!canManage.value) return;
  const response = await fetchProductColors({ page: 1, page_size: 500 });
  if (response.success) colors.value = collectionRows(response.data);
}

function search() {
  page.value = 1;
  return load();
}

function reset() {
  filters.search = '';
  filters.sales_status = '';
  filters.category_id = '';
  categoryTreeRef.value?.setCurrentKey(null);
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

function selectedMasterIds() {
  return selectedMasterRows.value.map((row) => row?.id).filter(Boolean);
}

function openBulkMasterEdit() {
  if (!canManage.value || !selectedMasterRows.value.length) {
    ElMessage.warning('请先勾选需要修改的商品');
    return;
  }
  Object.assign(bulkMasterForm, { product_name: '', category_node: null });
  bulkMasterVisible.value = true;
}

async function saveBulkMasterEdit() {
  if (!canManage.value || bulkMasterSaving.value) return;
  const ids = selectedMasterIds();
  const fields = {};
  if (bulkMasterForm.product_name.trim()) fields.product_name = bulkMasterForm.product_name.trim();
  if (bulkMasterForm.category_node) fields.category_node = bulkMasterForm.category_node;
  if (!ids.length || !Object.keys(fields).length) {
    ElMessage.warning('请至少填写一个修改字段并保留已勾选商品');
    return;
  }
  bulkMasterSaving.value = true;
  try {
    const response = await bulkUpdateProductSpus({ ids, fields });
    if (!response.success) {
      ElMessage.error(response.message || '批量修改商品失败');
      return;
    }
    bulkMasterVisible.value = false;
    selectedMasterRows.value = [];
    ElMessage.success(`批量修改完成，共处理 ${response.data?.updated ?? ids.length} 条商品`);
    await load();
  } finally {
    bulkMasterSaving.value = false;
  }
}

function openMoveCategory() {
  if (!canManage.value || !selectedMasterRows.value.length) {
    ElMessage.warning('请先勾选需要移动目录的商品');
    return;
  }
  moveCategoryNode.value = null;
  moveCategoryVisible.value = true;
}

async function saveMoveCategory() {
  if (!canManage.value || moveCategorySaving.value) return;
  if (!moveCategoryNode.value || !isUsableCategory(moveCategoryNode.value)) {
    ElMessage.warning('请选择启用的末级商品目录');
    return;
  }
  const ids = selectedMasterIds();
  if (!ids.length) {
    ElMessage.warning('请先勾选需要移动目录的商品');
    return;
  }
  moveCategorySaving.value = true;
  try {
    const response = await bulkUpdateProductSpus({ ids, fields: { category_node: moveCategoryNode.value }, operation: 'move_category' });
    if (!response.success) {
      ElMessage.error(response.message || '移动商品目录失败');
      return;
    }
    moveCategoryVisible.value = false;
    selectedMasterRows.value = [];
    ElMessage.success(`商品目录已移动，共处理 ${response.data?.updated ?? ids.length} 条商品`);
    await load();
  } finally {
    moveCategorySaving.value = false;
  }
}

function openCreate() {
  if (!canManage.value) return;
  Object.assign(createForm, { product_name: '', category_node: null, brand: '', season_code: '0' });
  createOpen.value = true;
}

async function saveProduct() {
  if (!canManage.value) return;
  if (!createForm.product_name?.trim() || !isUsableCategory(createForm.category_node)) {
    return ElMessage.warning('请填写商品名称并选择末级分类');
  }
  if (saving.value) return;
  saving.value = true;
  try {
    const response = await createProductSpu({
      ...createForm,
      category_node: createForm.category_node,
      product_name: createForm.product_name.trim(),
      product_type: 'standard'
    });
    if (!response.success) {
      ElMessage.error(response.message || '创建商品失败');
      return;
    }
    createOpen.value = false;
    ElMessage.success(`商品 ${detailData(response.data)?.spu_code || ''} 创建成功`);
    await load();
  } finally {
    saving.value = false;
  }
}

function openEdit(row) {
  if (!canManage.value || !row?.id) return;
  Object.assign(editForm, {
    id: row.id,
    product_name: row.product_name || '',
    category_node: row.category_node || null
  });
  editOpen.value = true;
}

async function saveEdit() {
  if (!canManage.value || editSaving.value) return;
  if (!editForm.id || !editForm.product_name?.trim() || !isUsableCategory(editForm.category_node)) {
    ElMessage.warning('请填写商品名称并选择启用的末级分类');
    return;
  }
  editSaving.value = true;
  try {
    const response = await updateProductSpu(editForm.id, {
      product_name: editForm.product_name.trim(),
      category_node: editForm.category_node
    });
    if (!response.success) {
      ElMessage.error(response.message || '保存商品失败');
      return;
    }
    editOpen.value = false;
    ElMessage.success('商品主数据已更新');
    await load();
  } finally {
    editSaving.value = false;
  }
}

function openSkuCreate(row) {
  if (!canManage.value || !row?.id) return;
  if (!isUsableCategory(row.category_node)) {
    ElMessage.warning('当前商品未绑定启用的末级分类，无法生成 SKU');
    return;
  }
  skuTarget.value = row;
  skuForm.color_code = '';
  skuForm.spec_values = Object.fromEntries(skuDimensions.value.map((dimension) => [dimension.code, '']));
  skuCreateOpen.value = true;
}

async function saveSku() {
  if (!canManage.value || skuSaving.value) return;
  if (!skuTarget.value?.id || !skuForm.color_code) {
    ElMessage.warning('请选择启用的颜色');
    return;
  }
  if (!activeColors.value.some((color) => color.code === skuForm.color_code)) {
    ElMessage.warning('请选择当前租户的启用颜色');
    return;
  }
  skuSaving.value = true;
  try {
    const response = await createProductSku({
      spu: skuTarget.value.id,
      color_code: skuForm.color_code,
      spec_values: { ...skuForm.spec_values }
    });
    if (!response.success) {
      ElMessage.error(response.message || 'SKU 生成失败');
      return;
    }
    skuCreateOpen.value = false;
    ElMessage.success(`SKU ${detailData(response.data)?.sku_code || ''} 已生成`);
    await load();
  } finally {
    skuSaving.value = false;
  }
}

onMounted(async () => {
  document.addEventListener('click', handleDocumentClick, true);
  await Promise.all([loadCategories(), loadColors()]);
  await load();
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
.pager,
.panel-title,
.header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-header p {
  margin: 4px 0 0;
  color: #64748b;
}

.header-copy {
  min-width: 0;
}

.page-subtitle {
  max-width: 720px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  color: #0f766e !important;
}

.coding-guide {
  max-width: 760px;
  margin-top: 10px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
}

.coding-guide summary {
  padding: 8px 12px;
  color: #0f766e;
  font-weight: 700;
  cursor: pointer;
}

.coding-guide summary::marker {
  color: #0f766e;
}

.coding-guide-content {
  display: grid;
  gap: 6px;
  padding: 0 12px 10px;
  font-size: 13px;
  line-height: 1.6;
}

.coding-guide-content p {
  margin: 0;
  color: #475569;
}

.coding-guide-content code {
  padding: 1px 4px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #334155;
  font-size: 12px;
}

.coding-guide-note {
  color: #64748b !important;
}

.workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 16px;
  min-width: 0;
}

.category-panel,
.filters {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.category-panel {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 500px;
}

.content-panel {
  display: grid;
  align-content: start;
  min-width: 0;
  gap: 16px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin: 0;
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

.row-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
}

.bulk-master-form {
  margin-top: 16px;
}

.bulk-master-form :deep(.el-tree-select),
.bulk-master-form :deep(.el-select),
.bulk-master-form :deep(.el-input) {
  width: 100%;
}

.product-master-table :deep(.product-category-tone-warm > td) {
  background-color: #fff4e6 !important;
}

.product-master-table :deep(.product-category-tone-0 > td) {
  background-color: #f0f9ff !important;
}

.product-master-table :deep(.product-category-tone-1 > td) {
  background-color: #f5f3ff !important;
}

.product-master-table :deep(.product-category-tone-2 > td) {
  background-color: #f0fdf4 !important;
}

.product-master-table :deep(.product-category-tone-3 > td) {
  background-color: #fff1f2 !important;
}

.product-master-table :deep(.product-category-tone-4 > td) {
  background-color: #f0fdfa !important;
}

.product-master-table :deep(.product-category-custom > td) {
  background-color: var(--product-category-row-background) !important;
}

.form-control {
  width: 100%;
}

.sku-form {
  margin-top: 16px;
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

.sku-details {
  display: grid;
  gap: 8px;
  white-space: normal;
  word-break: break-word;
}

:global(.sku-popover .sku-details) {
  max-height: 220px;
  overflow-x: hidden;
  overflow-y: auto;
}

.sku-details-subtitle {
  color: #64748b;
  font-size: 13px;
}

.sku-details-title {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.sku-details-list {
  display: grid;
  gap: 4px;
}

.sku-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 4px 0;
  border-bottom: 1px solid #eef2f7;
}

.sku-detail-code {
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: normal;
  word-break: break-all;
  color: #475569;
}

@media (max-width: 900px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .category-panel {
    min-height: auto;
    max-height: 300px;
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
