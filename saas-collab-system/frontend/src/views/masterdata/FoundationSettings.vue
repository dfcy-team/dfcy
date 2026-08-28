<template>
  <section class="foundation-settings-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">MASTER DATA</div>
        <h1>基础档案设置</h1>
        <p>集中维护基础档案在业务页面中的显示与选项规则。</p>
      </div>
    </header>

    <el-alert
      title="设置按当前租户保存，仅影响商品列表显示，不会修改商品分类归属或编码。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <h2>商品分类背景颜色</h2>
            <p>按二级类目设置商品主数据和商品明细数据的整行背景色。</p>
          </div>
          <el-button v-if="canManage" type="primary" :loading="saving" :disabled="!dirty" @click="save">
            保存设置
          </el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" border empty-text="当前租户暂无二级商品分类">
        <el-table-column prop="code" label="二级类目编码" width="140" />
        <el-table-column prop="name" label="二级类目名称" min-width="220" />
        <el-table-column label="颜色预览" width="150">
          <template #default="{ row }">
            <span class="color-preview" :style="{ backgroundColor: effectiveColor(row) }">
              {{ effectiveColor(row).toUpperCase() }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="自定义背景色" min-width="260">
          <template #default="{ row }">
            <div class="color-editor">
              <el-color-picker
                v-model="row.draftColor"
                :disabled="!canManage"
                :predefine="predefinedColors"
                color-format="hex"
              />
              <el-input v-model="row.draftColor" :disabled="!canManage" maxlength="7" placeholder="未设置时使用系统默认色" />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!canManage || !row.draftColor" @click="row.draftColor = ''">
              恢复默认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { fetchProductCategoryBackgroundColors, updateProductCategoryBackgroundColors } from '../../api/products';
import { useAuthStore } from '../../stores/auth';
import { collectionRows } from '../../utils/businessResponse';
import { defaultCategoryBackgroundColor } from '../../utils/productCategoryPresentation';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('masterdata.settings.manage'));
const loading = ref(false);
const saving = ref(false);
const rows = ref([]);
const predefinedColors = ['#fff4e6', '#f0f9ff', '#f5f3ff', '#f0fdf4', '#fff1f2', '#f0fdfa'];

const normalizeColor = (value) => String(value || '').trim().toUpperCase();
const effectiveColor = (row) => normalizeColor(row.draftColor) || defaultCategoryBackgroundColor(row);
const dirty = computed(() => rows.value.some((row) => normalizeColor(row.draftColor) !== normalizeColor(row.savedColor)));

async function load() {
  loading.value = true;
  const response = await fetchProductCategoryBackgroundColors();
  loading.value = false;
  if (!response.success) return ElMessage.error(response.message || '基础档案设置加载失败');
  rows.value = collectionRows(response.data).map((item) => ({
    ...item,
    savedColor: normalizeColor(item.row_background_color),
    draftColor: normalizeColor(item.row_background_color)
  }));
}

async function save() {
  const invalid = rows.value.find((row) => row.draftColor && !/^#[0-9A-Fa-f]{6}$/.test(row.draftColor));
  if (invalid) return ElMessage.warning(`${invalid.name} 的颜色格式应为 #RRGGBB`);
  saving.value = true;
  const response = await updateProductCategoryBackgroundColors(rows.value.map((row) => ({
    category_id: row.id,
    row_background_color: normalizeColor(row.draftColor)
  })));
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '保存失败');
  ElMessage.success('商品分类背景颜色已保存');
  await load();
}

onMounted(load);
</script>

<style scoped>
.foundation-settings-page { display: grid; gap: 16px; }
.page-header, .card-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; }
.page-header h1 { margin: 4px 0 6px; color: #12233f; font-size: 30px; }
.page-header p, .card-header p { margin: 0; color: #607087; }
.eyebrow { color: #0f766e; font-size: 12px; font-weight: 700; }
.settings-card { border-color: #d9e2ec; }
.card-header h2 { margin: 0 0 6px; color: #26364d; font-size: 18px; }
.color-editor { display: grid; grid-template-columns: 40px minmax(180px, 1fr); align-items: center; gap: 10px; }
.color-preview { display: inline-flex; align-items: center; justify-content: center; min-width: 100px; padding: 6px 10px; border: 1px solid rgba(15, 23, 42, .12); border-radius: 5px; color: #334155; font-family: monospace; }
@media (max-width: 760px) { .page-header, .card-header { align-items: flex-start; flex-direction: column; } }
</style>
