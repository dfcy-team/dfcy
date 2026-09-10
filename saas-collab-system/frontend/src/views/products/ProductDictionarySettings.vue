<template>
  <section class="business-page dictionary-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p class="page-subtitle">{{ subtitle }}</p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="canManage && supportsCreate"
          data-testid="dictionary-create"
          type="primary"
          @click="openCreate"
        >
          新增
        </el-button>
        <el-button data-testid="dictionary-refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-alert
      v-if="message"
      data-testid="dictionary-message"
      :title="message"
      type="error"
      show-icon
      :closable="false"
    />

    <div v-if="currentKind === 'categories'" class="category-workspace">
      <aside class="category-panel">
        <div class="panel-heading">
          <div>
            <strong>分类目录</strong>
            <span class="panel-caption">{{ rows.length }} 个分类</span>
          </div>
          <el-button link @click="selectCategory(null)">全部</el-button>
        </div>
        <el-input
          v-model="categoryFilter"
          data-testid="category-filter"
          clearable
          placeholder="搜索分类编码或名称"
        />
        <el-tree
          ref="categoryTreeRef"
          class="category-tree"
          data-testid="category-tree"
          :data="categoryTree"
          node-key="id"
          :props="{ label: 'displayName', children: 'children' }"
          :filter-node-method="filterCategory"
          :expand-on-click-node="false"
          default-expand-all
          highlight-current
          @node-click="selectCategory"
        >
          <template #default="{ data }">
            <div class="tree-node" :data-testid="`category-node-${data.id}`">
              <span class="tree-node-copy">
                <span class="tree-node-code">{{ data.code }}</span>
                <span>{{ data.name }}</span>
              </span>
              <span class="tree-node-actions">
                <el-tag size="small" effect="plain">L{{ data.level }}</el-tag>
                <el-button
                  v-if="canManage"
                  link
                  type="primary"
                  :data-testid="`category-edit-${data.id}`"
                  @click.stop="edit(data)"
                >
                  编辑
                </el-button>
                <el-button
                  v-if="canManage && Number(data.level) < 3"
                  link
                  type="primary"
                  :data-testid="`category-add-${data.id}`"
                  @click.stop="openCreateChild(data)"
                >
                  新增下级
                </el-button>
                <el-button
                  v-if="canManage && Number(data.level) > 1"
                  link
                  type="primary"
                  :data-testid="`category-move-${data.id}`"
                  @click.stop="openMove(data)"
                >
                  移动
                </el-button>
              </span>
            </div>
          </template>
        </el-tree>
        <el-empty v-if="!loading && !message && !categoryTree.length" description="暂无分类数据" :image-size="72" />
      </aside>

      <main class="dictionary-panel">
        <div class="panel-heading">
          <div>
            <strong>分类列表</strong>
            <span class="panel-caption">编码和层级用于生成商品 SPU</span>
          </div>
        </div>
        <el-table
          v-loading="loading"
          :data="categoryDisplayRows"
          row-key="id"
          border
          empty-text="暂无分类数据"
        >
          <el-table-column prop="level" label="层级" width="80">
            <template #default="{ row }">L{{ row.level }}</template>
          </el-table-column>
          <el-table-column prop="code" label="编码" width="110" />
          <el-table-column prop="name" label="中文名称" min-width="150" />
          <el-table-column label="上级分类" min-width="150">
            <template #default="{ row }">{{ parentName(row) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">{{ row.is_active === false ? '停用' : '启用' }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="210" fixed="right">
            <template #default="{ row }">
              <el-button v-if="canManage" link type="primary" @click="edit(row)">编辑</el-button>
              <el-button v-if="canManage && Number(row.level) > 1" link type="primary" @click="openMove(row)">移动</el-button>
              <el-button v-if="canManage" link type="primary" @click="toggleActive(row)">
                {{ row.is_active === false ? '启用' : '停用' }}
              </el-button>
              <el-button v-if="canManage" link type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </main>
    </div>

    <div v-else class="dictionary-panel standalone-panel">
      <div class="panel-heading">
        <div>
          <strong>{{ contentTitle }}</strong>
          <span class="panel-caption">{{ contentCaption }}</span>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="displayRows"
        row-key="id"
        border
        :empty-text="emptyText"
      >
        <template v-if="currentKind === 'attributes'">
          <el-table-column prop="code" label="属性编码" width="120" />
          <el-table-column prop="name" label="属性名称" min-width="220" />
          <el-table-column label="说明" min-width="260">
            <template #default="{ row }">用于生成商品 SPU 的一位属性编码：{{ row.code }}</template>
          </el-table-column>
        </template>
        <template v-else-if="currentKind === 'colors'">
          <el-table-column prop="code" label="颜色编码" width="150" />
          <el-table-column prop="name" label="颜色名称" min-width="220" />
        </template>
        <template v-else>
          <el-table-column prop="level" label="层级" width="80">
            <template #default="{ row }">L{{ row.level }}</template>
          </el-table-column>
          <el-table-column label="分类" min-width="220">
            <template #default="{ row }">{{ row.code }} {{ row.name }}</template>
          </el-table-column>
          <el-table-column label="规格维度（按顺序）" min-width="360">
            <template #default="{ row }">{{ formatDimensions(row.spec_dimensions) }}</template>
          </el-table-column>
        </template>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ row.is_active === false ? '停用' : '启用' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="190" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canManage" link type="primary" @click="edit(row)">
              {{ currentKind === 'specifications' ? '设置规格' : '编辑' }}
            </el-button>
            <el-button v-if="canManage && currentKind !== 'specifications'" link type="primary" @click="toggleActive(row)">
              {{ row.is_active === false ? '启用' : '停用' }}
            </el-button>
            <el-button v-if="canManage && currentKind !== 'specifications'" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !message && !displayRows.length" :description="emptyText" :image-size="72" />
    </div>

    <el-dialog v-model="visible" :title="dialogTitle" width="640px" destroy-on-close>
      <el-form label-position="top" @submit.prevent="save">
        <template v-if="currentKind === 'categories'">
          <el-form-item label="层级" required>
            <el-select
              v-model="form.level"
              data-testid="category-level"
              :disabled="Boolean(form.id)"
              @change="handleLevelChange"
            >
              <el-option v-for="level in 3" :key="level" :label="`L${level}`" :value="level" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="Number(form.level) > 1" label="上级分类" required>
            <el-select
              v-model="form.parent"
              data-testid="category-parent"
              filterable
              :disabled="dialogAction === 'edit'"
              placeholder="请选择上级分类"
            >
              <el-option
                v-for="parent in parentOptions"
                :key="parent.id"
                :label="`L${parent.level} ${parent.code} ${parent.name}`"
                :value="parent.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="dialogAction !== 'move'" label="分类编码" required>
            <el-input v-model="form.code" data-testid="category-code" :disabled="Boolean(form.id)" maxlength="2" />
          </el-form-item>
          <el-form-item v-if="dialogAction !== 'move'" label="中文名称" required>
            <el-input v-model="form.name" data-testid="category-name" maxlength="120" />
          </el-form-item>
          <el-form-item v-if="form.id" label="状态">
            <el-switch v-model="form.is_active" data-testid="category-active" active-text="启用" inactive-text="停用" />
          </el-form-item>
          <p v-if="dialogAction === 'move'" class="dialog-help">移动只调整上级分类，分类编码和层级保持不变。</p>
        </template>

        <template v-else-if="currentKind === 'attributes'">
          <el-form-item label="属性编码">
            <el-input v-if="form.id" v-model="form.code" disabled />
            <p v-else class="generated-code-note">保存后按现有字典顺序自动生成 1–9 的一位编码。</p>
          </el-form-item>
          <el-form-item label="属性名称" required>
            <el-input v-model="form.name" data-testid="attribute-name" maxlength="80" placeholder="例如：季节" />
          </el-form-item>
          <el-form-item v-if="form.id" label="状态">
            <el-switch v-model="form.is_active" data-testid="attribute-active" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </template>

        <template v-else-if="currentKind === 'colors'">
          <el-form-item label="颜色编码" required>
            <el-input v-model="form.code" data-testid="color-code" maxlength="40" placeholder="例如：black" />
          </el-form-item>
          <el-form-item label="颜色名称" required>
            <el-input v-model="form.name" data-testid="color-name" maxlength="80" placeholder="例如：黑色" />
          </el-form-item>
          <el-form-item v-if="form.id" label="状态">
            <el-switch v-model="form.is_active" data-testid="color-active" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="适用分类">
            <el-input :model-value="`${form.code || ''} ${form.name || ''}`.trim()" disabled />
          </el-form-item>
          <el-form-item label="规格维度" required>
            <div class="dimension-list" data-testid="spec-dimensions">
              <div v-for="(dimension, index) in form.dimensions" :key="dimension.key" class="dimension-row">
                <el-input v-model="dimension.code" placeholder="编码，如 size" :data-testid="`spec-code-${index}`" />
                <el-input v-model="dimension.name" placeholder="名称，如 尺寸" :data-testid="`spec-name-${index}`" />
                <el-input v-model="dimension.valuesText" placeholder="选项值，用逗号分隔" :data-testid="`spec-values-${index}`" />
                <el-button link type="danger" @click="removeDimension(index)">删除</el-button>
              </div>
              <el-button data-testid="spec-add-dimension" @click="addDimension">添加规格维度</el-button>
            </div>
          </el-form-item>
          <p class="dialog-help">每个规格维度包含编码、名称和可选值；选项值会保留并用于后续 SKU 生成。</p>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button data-testid="dictionary-save" type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import {
  createProductAttribute,
  createProductCategory,
  createProductColor,
  deleteProductAttribute,
  deleteProductCategory,
  deleteProductColor,
  fetchProductAttributes,
  fetchProductCategories,
  fetchProductColors,
  updateProductAttribute,
  updateProductAttributes,
  updateProductCategory,
  updateProductColor
} from '../../api/products';
import { collectionRows } from '../../utils/businessResponse';
import { invalidateProductDictionaryCache } from '../../utils/productDictionaryCache';

const props = defineProps({
  kind: { type: String, default: '' },
  mode: { type: String, default: '' }
});

const KIND_ALIASES = {
  category: 'categories',
  categories: 'categories',
  attribute: 'attributes',
  attributes: 'attributes',
  color: 'colors',
  colors: 'colors',
  specification: 'specifications',
  specifications: 'specifications'
};

const CONFIG = {
  categories: {
    title: '分类设置',
    subtitle: '维护三级商品分类、编码和分类层级。',
    contentTitle: '分类目录',
    contentCaption: '移动分类时只调整上级分类，不会改变编码和层级。',
    emptyText: '暂无分类数据',
    viewPermissions: ['products.category.view', 'products.master.view'],
    managePermissions: ['products.category.manage', 'products.master.manage']
  },
  attributes: {
    title: '属性设置',
    subtitle: '维护用于商品编码的属性名称和一位属性编码字典。',
    contentTitle: '商品属性字典',
    contentCaption: '新属性按 1–9 顺序自动分配编码，商品编码会引用这里的属性编码。',
    emptyText: '暂无属性字典',
    viewPermissions: ['products.attribute.view', 'products.master.view'],
    managePermissions: ['products.attribute.manage', 'products.specification.manage', 'products.master.manage']
  },
  colors: {
    title: '颜色设置',
    subtitle: '维护 SKU 使用的颜色编码字典。',
    contentTitle: '颜色编码字典',
    contentCaption: '颜色编码用于生成 SKU；已被 SKU 使用的编码需先确认业务影响。',
    emptyText: '暂无颜色字典',
    viewPermissions: ['products.color.view', 'products.master.view'],
    managePermissions: ['products.color.manage', 'products.master.manage']
  },
  specifications: {
    title: '规格设置',
    subtitle: '为末级分类维护 SKU 规格维度和编码顺序。',
    contentTitle: '分类规格维度',
    contentCaption: '显示 L3 分类，以及没有 L3 下级的 L2 分类。',
    emptyText: '暂无可配置规格的末级分类',
    viewPermissions: ['products.specification.view', 'products.attribute.view', 'products.master.view'],
    managePermissions: ['products.specification.manage', 'products.attribute.manage', 'products.master.manage']
  }
};

const auth = useAuthStore();
const rows = ref([]);
const loading = ref(false);
const saving = ref(false);
const message = ref('');
const visible = ref(false);
const dialogAction = ref('create');
const categoryFilter = ref('');
const selectedCategory = ref(null);
const categoryTreeRef = ref(null);
const form = reactive({
  id: null,
  parent: null,
  level: 1,
  code: '',
  name: '',
  is_active: true,
  dimensions: []
});

const currentKind = computed(() => KIND_ALIASES[props.kind || props.mode] || 'categories');
const config = computed(() => CONFIG[currentKind.value]);
const title = computed(() => config.value.title);
const subtitle = computed(() => config.value.subtitle);
const contentTitle = computed(() => config.value.contentTitle);
const contentCaption = computed(() => config.value.contentCaption);
const emptyText = computed(() => config.value.emptyText);
const canManage = computed(() => auth.hasPermission(...config.value.managePermissions));
const supportsCreate = computed(() => ['categories', 'attributes', 'colors'].includes(currentKind.value));
const dialogTitle = computed(() => {
  if (currentKind.value === 'specifications') return '设置规格';
  if (dialogAction.value === 'move') return '移动分类';
  const noun = currentKind.value === 'categories' ? '分类' : currentKind.value === 'attributes' ? '属性' : '颜色';
  return `${form.id ? '编辑' : '新增'}${noun}`;
});
const parentOptions = computed(() => {
  if (currentKind.value !== 'categories' || Number(form.level) <= 1) return [];
  return rows.value.filter((item) => {
    if (Number(item.level) !== Number(form.level) - 1) return false;
    if (!form.id) return true;
    return Number(item.id) !== Number(form.id) && !isDescendant(item.id, form.id);
  });
});
const categoryTree = computed(() => buildCategoryTree(rows.value));
const specificationRows = computed(() => {
  const l3ParentIds = new Set(
    rows.value
      .filter((item) => Number(item.level) === 3)
      .map((item) => String(parentIdOf(item)))
  );
  return rows.value.filter((item) => {
    const level = Number(item.level);
    return level === 3 || (level === 2 && !l3ParentIds.has(String(item.id)));
  });
});
const displayRows = computed(() => (currentKind.value === 'specifications' ? specificationRows.value : rows.value));
const categoryDisplayRows = computed(() => {
  if (!selectedCategory.value) return rows.value;
  return rows.value.filter((item) => (
    String(item.id) === String(selectedCategory.value.id)
    || isDescendant(item.id, selectedCategory.value.id)
  ));
});

let latestLoadRequest = 0;

function parentIdOf(item) {
  return item?.parent_id ?? item?.parent ?? null;
}

function normalizeRows(data) {
  return collectionRows(data).map((item) => ({
    ...item,
    level: Number(item.level || 0),
    parent: parentIdOf(item),
    parent_id: parentIdOf(item),
    displayName: `${item.code || ''} ${item.name || ''}`.trim(),
    is_active: item.is_active !== false
  }));
}

function buildCategoryTree(items) {
  const nodes = new Map(items.map((item) => [String(item.id), { ...item, children: [] }]));
  const roots = [];
  nodes.forEach((node) => {
    const parent = nodes.get(String(parentIdOf(node)));
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (list) => {
    list.sort((a, b) => Number(a.level) - Number(b.level) || String(a.code).localeCompare(String(b.code), 'zh-CN') || Number(a.id) - Number(b.id));
    list.forEach((node) => sortNodes(node.children));
    return list;
  };
  return sortNodes(roots);
}

function isDescendant(candidateId, ancestorId) {
  const visited = new Set();
  let current = rows.value.find((item) => String(item.id) === String(candidateId));
  while (current && parentIdOf(current) != null && !visited.has(String(current.id))) {
    visited.add(String(current.id));
    if (String(parentIdOf(current)) === String(ancestorId)) return true;
    current = rows.value.find((item) => String(item.id) === String(parentIdOf(current)));
  }
  return false;
}

function parentName(row) {
  const parent = rows.value.find((item) => String(item.id) === String(parentIdOf(row)));
  return parent ? `${parent.code} ${parent.name}` : '—';
}

function formatDimensions(dimensions) {
  if (!Array.isArray(dimensions) || !dimensions.length) return '未设置';
  return dimensions
    .map((item) => {
      const values = Array.isArray(item.values) && item.values.length ? `：${item.values.join('、')}` : '';
      return `${item.name || item.code}(${item.code})${values}`;
    })
    .join('、');
}

function cloneValue(value) {
  if (value === undefined) return undefined;
  try {
    return structuredClone(value);
  } catch (_error) {
    return JSON.parse(JSON.stringify(value));
  }
}

function formatDimensionValues(values) {
  if (!Array.isArray(values)) return values == null ? '' : String(values);
  return values
    .map((value) => (value && typeof value === 'object' ? JSON.stringify(value) : String(value)))
    .join(', ');
}

function parseDimensionValues(text) {
  return String(text || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function dimensionForm(item = {}) {
  const hasValues = Object.prototype.hasOwnProperty.call(item, 'values');
  const originalValues = hasValues ? cloneValue(item.values) : undefined;
  return {
    key: `${Date.now()}-${Math.random()}`,
    code: String(item.code || ''),
    name: String(item.name || ''),
    valuesText: formatDimensionValues(item.values),
    originalValuesText: formatDimensionValues(item.values),
    hasValues,
    originalValues
  };
}

function serializeDimensions() {
  return form.dimensions
    .map((item) => {
      const code = String(item.code || '').trim();
      const name = String(item.name || '').trim();
      const next = { code, name };
      if (item.hasValues || String(item.valuesText || '').trim()) {
        const unchanged = String(item.valuesText || '').trim() === String(item.originalValuesText || '').trim();
        const preservedValues = cloneValue(item.originalValues);
        next.values = unchanged && preservedValues !== undefined ? preservedValues : parseDimensionValues(item.valuesText);
      }
      return next;
    })
    .filter((item) => item.code || item.name || item.values);
}

async function load() {
  const requestId = ++latestLoadRequest;
  loading.value = true;
  message.value = '';
  rows.value = [];
  try {
    let response;
    if (currentKind.value === 'attributes') response = await fetchProductAttributes();
    else if (currentKind.value === 'colors') response = await fetchProductColors();
    else response = await fetchProductCategories();
    if (!response?.success) throw new Error(response?.message || '基础字典加载失败');
    if (requestId !== latestLoadRequest) return;
    rows.value = normalizeRows(response.data);
    if (selectedCategory.value && !rows.value.some((item) => String(item.id) === String(selectedCategory.value.id))) {
      selectedCategory.value = null;
    }
  } catch (error) {
    if (requestId !== latestLoadRequest) return;
    message.value = error?.message || '基础字典加载失败';
  } finally {
    if (requestId === latestLoadRequest) loading.value = false;
  }
}

function filterCategory(value, data) {
  if (!value) return true;
  return `${data.code || ''} ${data.name || ''}`.toLowerCase().includes(String(value).toLowerCase());
}

watch(categoryFilter, (value) => {
  nextTick(() => categoryTreeRef.value?.filter?.(value));
});

function selectCategory(node) {
  selectedCategory.value = node || null;
}

function resetForm(values = {}) {
  Object.assign(form, {
    id: null,
    parent: null,
    level: 1,
    code: '',
    name: '',
    is_active: true,
    dimensions: [],
    ...values
  });
}

function openCreate() {
  if (!supportsCreate.value || !canManage.value) return;
  dialogAction.value = 'create';
  resetForm();
  visible.value = true;
}

function openCreateChild(parent) {
  if (!canManage.value || Number(parent.level) >= 3) return;
  dialogAction.value = 'create';
  resetForm({ level: Number(parent.level) + 1, parent: parent.id });
  visible.value = true;
}

function edit(row) {
  if (!canManage.value) return;
  dialogAction.value = 'edit';
  if (currentKind.value === 'specifications') {
    resetForm({
      id: row.id,
      code: row.code,
      name: row.name,
      level: Number(row.level),
      dimensions: (Array.isArray(row.spec_dimensions) ? row.spec_dimensions : []).map(dimensionForm)
    });
  } else {
    resetForm({
      id: row.id,
      parent: parentIdOf(row),
      level: Number(row.level || 1),
      code: row.code || '',
      name: row.name || '',
      is_active: row.is_active !== false
    });
  }
  visible.value = true;
}

function openMove(row) {
  if (!canManage.value || Number(row.level) <= 1) return;
  dialogAction.value = 'move';
  resetForm({
    id: row.id,
    parent: parentIdOf(row),
    level: Number(row.level),
    code: row.code || '',
    name: row.name || '',
    is_active: row.is_active !== false
  });
  visible.value = true;
}

function handleLevelChange() {
  if (Number(form.level) <= 1) form.parent = null;
  else if (!parentOptions.value.some((item) => String(item.id) === String(form.parent))) form.parent = null;
}

function addDimension() {
  form.dimensions.push(dimensionForm());
}

function removeDimension(index) {
  form.dimensions.splice(index, 1);
}

function validForm() {
  if (currentKind.value === 'categories') {
    if (dialogAction.value !== 'move' && !String(form.code || '').trim()) return '请输入分类编码';
    if (dialogAction.value !== 'move' && !String(form.name || '').trim()) return '请输入分类名称';
    if (Number(form.level) > 1 && !form.parent) return '请选择上级分类';
    return '';
  }
  if (currentKind.value === 'attributes') return String(form.name || '').trim() ? '' : '请输入属性名称';
  if (currentKind.value === 'colors') {
    if (!String(form.code || '').trim()) return '请输入颜色编码';
    if (!String(form.name || '').trim()) return '请输入颜色名称';
    return '';
  }
  const dimensions = serializeDimensions();
  if (dimensions.some((item) => !item.code || !item.name)) return '请完整填写规格编码和名称';
  const codes = dimensions.map((item) => item.code);
  if (new Set(codes).size !== codes.length) return '规格编码不能重复';
  return '';
}

async function save() {
  if (saving.value) return;
  if (!canManage.value) {
    ElMessage.warning('当前没有维护权限');
    return;
  }
  const validationMessage = validForm();
  if (validationMessage) {
    ElMessage.warning(validationMessage);
    return;
  }
  saving.value = true;
  try {
    let response;
    if (currentKind.value === 'categories') {
      if (dialogAction.value === 'move') {
        response = await updateProductCategory(form.id, { parent: form.parent || null });
      } else if (form.id) {
        response = await updateProductCategory(form.id, { name: String(form.name).trim(), is_active: form.is_active });
      } else {
        response = await createProductCategory({
          level: Number(form.level),
          parent: Number(form.level) > 1 ? form.parent : null,
          code: String(form.code).trim(),
          name: String(form.name).trim(),
          is_active: form.is_active
        });
      }
    } else if (currentKind.value === 'attributes') {
      response = form.id
        ? await updateProductAttribute(form.id, { name: String(form.name).trim(), is_active: form.is_active })
        : await createProductAttribute({ name: String(form.name).trim(), is_active: true });
    } else if (currentKind.value === 'colors') {
      const payload = { code: String(form.code).trim(), name: String(form.name).trim(), is_active: form.is_active };
      response = form.id ? await updateProductColor(form.id, payload) : await createProductColor(payload);
    } else {
      response = await updateProductAttributes(form.id, serializeDimensions());
    }
    if (!response?.success) throw new Error(response?.message || '保存失败');
    invalidateProductDictionaryCache();
    ElMessage.success('保存成功');
    visible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '保存失败');
  } finally {
    saving.value = false;
  }
}

async function toggleActive(row) {
  if (!canManage.value) return;
  const next = row.is_active === false;
  try {
    let response;
    if (currentKind.value === 'categories') response = await updateProductCategory(row.id, { is_active: next });
    else if (currentKind.value === 'attributes') response = await updateProductAttribute(row.id, { is_active: next });
    else if (currentKind.value === 'colors') response = await updateProductColor(row.id, { is_active: next });
    else return;
    if (!response?.success) throw new Error(response?.message || '状态保存失败');
    invalidateProductDictionaryCache();
    ElMessage.success(next ? '已启用' : '已停用');
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '状态保存失败');
  }
}

async function remove(row) {
  if (!canManage.value || currentKind.value === 'specifications') return;
  try {
    await ElMessageBox.confirm(`确认删除“${row.name || row.code}”吗？`, '删除确认', { type: 'warning' });
  } catch (_error) {
    return;
  }
  try {
    let response;
    if (currentKind.value === 'categories') response = await deleteProductCategory(row.id);
    else if (currentKind.value === 'attributes') response = await deleteProductAttribute(row.id);
    else response = await deleteProductColor(row.id);
    if (!response?.success) throw new Error(response?.message || '删除失败');
    invalidateProductDictionaryCache();
    ElMessage.success('删除成功');
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '删除失败');
  }
}

watch(currentKind, () => {
  visible.value = false;
  dialogAction.value = 'create';
  selectedCategory.value = null;
  resetForm();
  load();
});

onMounted(load);
</script>

<style scoped>
.dictionary-page { display: grid; gap: 16px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.page-title { margin: 0; color: #102a43; font-size: 24px; line-height: 1.3; }
.page-subtitle { margin: 8px 0 0; color: #64748b; font-size: 14px; }
.header-actions { display: flex; gap: 10px; align-items: center; }
.category-workspace { display: grid; grid-template-columns: minmax(320px, 360px) minmax(0, 1fr); gap: 16px; align-items: start; }
.category-panel, .dictionary-panel { min-width: 0; padding: 16px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
.standalone-panel { overflow: hidden; }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; color: #243b53; }
.panel-heading > div { display: grid; gap: 4px; }
.panel-caption { color: #829ab1; font-size: 12px; font-weight: 400; }
.category-tree { margin-top: 14px; }
.tree-node { display: flex; align-items: center; justify-content: space-between; width: 100%; min-width: 0; gap: 8px; padding: 2px 0; }
.tree-node-copy { display: flex; min-width: 0; align-items: center; gap: 7px; overflow: hidden; }
.tree-node-copy > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree-node-code { color: #52606d; font-variant-numeric: tabular-nums; }
.tree-node-actions { display: none; flex: 0 0 auto; align-items: center; gap: 2px; }
.tree-node:hover .tree-node-actions, .tree-node:focus-within .tree-node-actions { display: flex; }
.tree-node-actions :deep(.el-button) { padding: 2px 3px; font-size: 12px; }
.dimension-list { display: grid; width: 100%; gap: 10px; }
.dimension-row { display: grid; grid-template-columns: 1fr 1.2fr 1.5fr auto; gap: 8px; align-items: center; }
.dialog-help, .generated-code-note { margin: -4px 0 4px; color: #64748b; font-size: 12px; line-height: 1.6; }
@media (max-width: 900px) {
  .category-workspace { grid-template-columns: 1fr; }
  .tree-node-actions { display: flex; }
  .dimension-row { grid-template-columns: 1fr 1fr; }
  .dimension-row :deep(.el-button) { justify-self: start; }
}
</style>
