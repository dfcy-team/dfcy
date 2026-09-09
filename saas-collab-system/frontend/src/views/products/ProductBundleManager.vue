<template>
  <section class="business-page">
    <header class="page-header">
      <div>
        <h1>组合商品</h1>
        <p>选择多个已有普通 SKU，生成组合 SPU / SKU；也可批量导入并生成 BigSeller 表。</p>
      </div>
      <div class="header-actions">
        <el-dropdown v-if="canManage" trigger="click" @command="handleIoCommand">
          <el-button data-testid="bundle-io-menu">导入与导出 <span class="io-menu-caret">⌄</span></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>导入</el-dropdown-item>
              <el-dropdown-item command="bundle-import" data-testid="bundle-import-button">组合商品导入</el-dropdown-item>
              <el-dropdown-item divided disabled>导出</el-dropdown-item>
              <el-dropdown-item command="bigseller-export" data-testid="bigseller-create-bundle-export" :disabled="!selectedBundles.length || importing">
                下载 BigSeller 组合商品SKU表
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button
          v-if="canManage"
          data-testid="bundle-create-button"
          type="primary"
          @click="visible = true"
        >新建组合 SKU</el-button>
      </div>
    </header>

    <el-alert
      title="BigSeller 组合表最多包含 20 个子 SKU；批量导入成功后会自动下载。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-table :data="bundles" row-key="id" border @selection-change="selectedBundles = $event">
      <el-table-column v-if="canManage" type="selection" width="48" reserve-selection />
      <el-table-column prop="spu_code" label="组合 SPU" min-width="150" />
      <el-table-column prop="product_name" label="组合商品名称" min-width="220" />
      <el-table-column label="组合 SKU" min-width="220">
        <template #default="{ row }">{{ bundleSkuCodes(row) || '-' }}</template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" title="由现有 SKU 创建组合 SKU" width="720px">
      <el-form label-position="top">
        <el-form-item label="组合商品名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="末级分类">
          <el-select v-model="form.category" filterable>
            <el-option v-for="item in leaves" :key="item.id" :label="`${item.code} ${item.name}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="季节">
          <el-select v-model="form.season">
            <el-option v-for="item in options.seasons" :key="item.code" :label="item.name" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="组合颜色">
          <el-select v-model="form.color">
            <el-option v-for="item in colors" :key="item.code" :label="`${item.name} (${item.code})`" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="组成 SKU">
          <div class="components">
            <div v-for="(item, index) in form.components" :key="index">
              <el-select v-model="item.sku" filterable>
                <el-option v-for="sku in normalSkus" :key="sku.id" :label="sku.sku_code" :value="sku.id" />
              </el-select>
              <el-input-number v-model="item.quantity" :min="1" />
              <el-button @click="form.components.splice(index, 1)">删除</el-button>
            </div>
            <el-button :disabled="form.components.length >= 20" @click="addFormComponent">添加现有 SKU</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">生成组合 SKU</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bundleImportVisible" title="组合商品导入" width="min(560px, 94vw)">
      <input ref="bundleImportInput" data-testid="bundle-import-file" hidden type="file" accept=".csv,text/csv" @change="selectBundleImportFile" />
      <div class="import-upload-box" role="button" tabindex="0" @click="bundleImportInput?.click()" @keydown.enter="bundleImportInput?.click()">
        <span class="import-upload-icon">⇧</span>
        <strong>{{ bundleImportFileName || '点击选择 CSV 文件' }}</strong>
        <small>导入成功后将自动生成组合 SPU / SKU 并下载 BigSeller 表</small>
      </div>
      <el-button data-testid="bundle-import-template" class="import-template-link" link type="primary" @click="downloadBundleImportTemplate">下载组合商品导入模板</el-button>
      <template #footer>
        <el-button @click="bundleImportVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!bundleImportUpload" @click="confirmBundleImport">确定导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importSummaryVisible" title="组合商品导入结果" width="min(760px, 94vw)">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="文件">{{ importSummary.fileName || '-' }}</el-descriptions-item>
        <el-descriptions-item label="成功">{{ importSummary.created }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ importSummary.errors.length }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="importSummary.created"
        class="summary-alert"
        title="已为导入成功的组合 SKU 生成 BigSeller 组合商品SKU表。"
        type="success"
        :closable="false"
      />
      <el-table v-if="importSummary.errors.length" :data="importSummary.errors" border max-height="300">
        <el-table-column prop="line" label="CSV 行号" width="100" />
        <el-table-column prop="message" label="错误原因" min-width="480" />
      </el-table>
      <template #footer><el-button type="primary" @click="importSummaryVisible = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import {
  createBundleComponent,
  createProductSku,
  createProductSpu,
  fetchBundleComponents,
  fetchCodingOptions,
  fetchProductCategories,
  fetchProductColors,
  fetchProductMasterList,
  fetchProductSkuList,
} from '../../api/products';
import { collectionRows, detailData } from '../../utils/businessResponse';
import { downloadBigSellerBundleWorkbook } from '../../utils/bigsellerWorkbook';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.bundle.manage'));
const spus = ref([]);
const skus = ref([]);
const bundleComponents = ref([]);
const categories = ref([]);
const colors = ref([]);
const options = reactive({ seasons: [] });
const visible = ref(false);
const saving = ref(false);
const importing = ref(false);
const bundleImportVisible = ref(false);
const bundleImportInput = ref(null);
const bundleImportUpload = ref(null);
const bundleImportFileName = ref('');
const selectedBundles = ref([]);
const importSummaryVisible = ref(false);
const importSummary = reactive({ fileName: '', created: 0, errors: [] });
const form = reactive({ name: '', category: null, season: '5', color: null, components: [{ sku: null, quantity: 1 }] });

const bundles = computed(() => spus.value.filter((item) => item.product_type === 'bundle'));
const leaves = computed(() => categories.value.filter((item) => item.level === 3 && item.is_active));
const normalSkus = computed(() => {
  const ids = new Set(spus.value.filter((item) => item.product_type !== 'bundle').map((item) => item.id));
  return skus.value.filter((item) => ids.has(item.spu));
});

function bundleSkuCodes(row) {
  return skus.value.filter((item) => String(item.spu) === String(row.id)).map((item) => item.sku_code).join('、');
}

async function load() {
  const [spuResponse, skuResponse, categoryResponse, colorResponse, optionResponse, componentResponse] = await Promise.all([
    fetchProductMasterList({ page_size: 100 }),
    fetchProductSkuList({ page_size: 100 }),
    fetchProductCategories(),
    fetchProductColors(),
    fetchCodingOptions(),
    fetchBundleComponents(),
  ]);
  spus.value = collectionRows(spuResponse.data);
  skus.value = collectionRows(skuResponse.data);
  categories.value = collectionRows(categoryResponse.data);
  colors.value = collectionRows(colorResponse.data);
  bundleComponents.value = collectionRows(componentResponse.data);
  Object.assign(options, detailData(optionResponse.data));
}

function addFormComponent() {
  if (form.components.length < 20) form.components.push({ sku: null, quantity: 1 });
}

async function createBundle({ name, category, season, color, components }) {
  const productResponse = await createProductSpu({ product_name: name, category_node: category, season_code: season, product_type: 'bundle' });
  if (!productResponse.success) throw new Error(productResponse.message || '组合 SPU 创建失败');
  const spu = detailData(productResponse.data);
  const categoryRecord = categories.value.find((item) => String(item.id) === String(category));
  const specValues = Object.fromEntries((categoryRecord?.spec_dimensions || []).map((item) => [item.code, '组合']));
  const skuResponse = await createProductSku({ spu: spu.id, color_code: color, spec_values: specValues });
  if (!skuResponse.success) throw new Error(skuResponse.message || '组合 SKU 创建失败');
  const sku = detailData(skuResponse.data);
  const createdComponents = [];
  for (const component of components) {
    const componentResponse = await createBundleComponent({ bundle_sku: sku.id, component_sku: component.sku, quantity: component.quantity });
    if (!componentResponse.success) throw new Error(componentResponse.message || `组成 SKU ${component.skuCode || component.sku} 保存失败`);
    createdComponents.push({
      ...detailData(componentResponse.data),
      bundle_sku: sku.id,
      component_sku: component.sku,
      component_sku_code: component.skuCode || normalSkus.value.find((item) => String(item.id) === String(component.sku))?.sku_code || '',
      quantity: component.quantity,
      cost_allocation_ratio: component.costRatio ?? 1,
    });
  }
  return { spu, sku, components: createdComponents };
}

async function save() {
  if (!form.name || !form.category || !form.color || !form.components.length || form.components.some((item) => !item.sku)) {
    ElMessage.warning('请完整填写组合商品及组成 SKU');
    return;
  }
  saving.value = true;
  try {
    const result = await createBundle({ ...form, components: form.components });
    visible.value = false;
    ElMessage.success(`组合 SKU ${result.sku.sku_code} 已生成`);
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '组合 SKU 创建失败');
  } finally {
    saving.value = false;
  }
}

function parseCsvRows(text) {
  const source = String(text || '').replace(/^\uFEFF/, '');
  const output = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];
    if (character === '"' && quoted && next === '"') { cell += '"'; index += 1; continue; }
    if (character === '"') { quoted = !quoted; continue; }
    if (character === ',' && !quoted) { row.push(cell.trim()); cell = ''; continue; }
    if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && next === '\n') index += 1;
      row.push(cell.trim());
      if (row.some((value) => value !== '')) output.push(row);
      row = [];
      cell = '';
      continue;
    }
    cell += character;
  }
  row.push(cell.trim());
  if (row.some((value) => value !== '')) output.push(row);
  return output;
}

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv(filename, headers, values) {
  const csv = `\ufeff${headers.map(csvCell).join(',')}\n${values.map(csvCell).join(',')}\n`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function bundleImportHeaders() {
  return [
    '*组合商品名称', '*末级分类编码', '*季节编码', '*组合颜色英文编码',
    ...Array.from({ length: 20 }, (_, index) => {
      const number = index + 1;
      const required = number === 1 ? '*' : '';
      return [`${required}单品SKU${number}`, `${required}SKU${number}数量`, `SKU${number}成本价分摊比`];
    }).flat(),
  ];
}

function downloadBundleImportTemplate() {
  const headers = bundleImportHeaders();
  const values = Array(headers.length).fill('');
  [values[0], values[1], values[2], values[3], values[4], values[5], values[6]] = ['示例组合商品', '10101', '5', 'white', 'NORMAL-SKU-001', 1, 1];
  downloadCsv('组合商品导入模板.csv', headers, values);
}

function openBundleImport() {
  bundleImportUpload.value = null;
  bundleImportFileName.value = '';
  bundleImportVisible.value = true;
}

function handleIoCommand(command) {
  if (command === 'bundle-import') openBundleImport();
  else if (command === 'bigseller-export') exportSelectedBundles();
}

function selectBundleImportFile(event) {
  const uploadedFile = event.target.files?.[0] || null;
  event.target.value = '';
  if (!uploadedFile) return;
  if (!/\.csv$/i.test(uploadedFile.name)) { ElMessage.warning('请选择 CSV 文件'); return; }
  bundleImportUpload.value = uploadedFile;
  bundleImportFileName.value = uploadedFile.name;
}

function confirmBundleImport() {
  if (!bundleImportUpload.value) return;
  const uploadedFile = bundleImportUpload.value;
  bundleImportVisible.value = false;
  importBundleFile(uploadedFile);
}

function headerIndex(headers, name) {
  const normalizedName = name.replace(/^\*/, '');
  return headers.findIndex((header) => String(header || '').replace(/^\*/, '').trim() === normalizedName);
}

function importValue(values, headers, name) {
  const index = headerIndex(headers, name);
  return index < 0 ? '' : String(values[index] ?? '').trim();
}

function prepareImportRow(values, headers, line) {
  const name = importValue(values, headers, '组合商品名称');
  const categoryCode = importValue(values, headers, '末级分类编码');
  const season = importValue(values, headers, '季节编码');
  const color = importValue(values, headers, '组合颜色英文编码');
  if (!name || !categoryCode || !season || !color) throw new Error('组合商品名称、末级分类编码、季节编码、组合颜色英文编码为必填');
  const category = leaves.value.find((item) => String(item.code) === categoryCode);
  if (!category) throw new Error(`末级分类编码 ${categoryCode} 不存在或已停用`);
  if (!colors.value.some((item) => String(item.code) === color && item.is_active !== false)) throw new Error(`颜色编码 ${color} 不存在或已停用`);
  const components = [];
  for (let index = 1; index <= 20; index += 1) {
    const skuCode = importValue(values, headers, `单品SKU${index}`);
    const quantityValue = importValue(values, headers, `SKU${index}数量`);
    const costRatioValue = importValue(values, headers, `SKU${index}成本价分摊比`);
    if (!skuCode && !quantityValue && !costRatioValue) continue;
    const sku = normalSkus.value.find((item) => String(item.sku_code) === skuCode);
    if (!sku) throw new Error(`单品 SKU ${skuCode || index} 不存在`);
    const quantity = Number(quantityValue);
    if (!Number.isInteger(quantity) || quantity < 1) throw new Error(`SKU${index}数量必须是大于 0 的整数`);
    const costRatio = costRatioValue === '' ? 1 : Number(costRatioValue);
    if (!Number.isFinite(costRatio) || costRatio < 0) throw new Error(`SKU${index}成本价分摊比必须是非负数`);
    components.push({ sku: sku.id, skuCode, quantity, costRatio });
  }
  if (!components.length) throw new Error('至少填写一个单品 SKU 及数量');
  return { line, name, category: category.id, season, color, components };
}

async function importBundleFile(file) {
  importing.value = true;
  importSummary.fileName = file.name;
  importSummary.created = 0;
  importSummary.errors = [];
  const createdSpus = [];
  const createdSkus = [];
  const createdComponents = [];
  try {
    const rows = parseCsvRows(await file.text());
    if (rows.length < 2) throw new Error('CSV 中没有可导入数据');
    const headers = rows[0];
    for (let index = 1; index < rows.length; index += 1) {
      try {
        const result = await createBundle(prepareImportRow(rows[index], headers, index + 1));
        createdSpus.push(result.spu);
        createdSkus.push(result.sku);
        createdComponents.push(...result.components);
        importSummary.created += 1;
      } catch (error) {
        importSummary.errors.push({ line: index + 1, message: error?.message || '导入失败' });
      }
    }
    if (createdSkus.length) {
      downloadBigSellerBundleWorkbook(createdSpus, createdSkus, createdComponents);
      ElMessage.success(`已导入 ${createdSkus.length} 个组合 SKU 并生成 BigSeller 表`);
      await load();
    } else {
      ElMessage.warning('未导入任何组合商品，请根据错误修正后重试');
    }
  } catch (error) {
    importSummary.errors.push({ line: '-', message: error?.message || '导入失败' });
    ElMessage.error(error?.message || '组合商品导入失败');
  } finally {
    importing.value = false;
    importSummaryVisible.value = true;
  }
}

function exportSelectedBundles() {
  try {
    const count = downloadBigSellerBundleWorkbook(selectedBundles.value, skus.value, bundleComponents.value);
    ElMessage.success(`已生成 ${count} 条 BigSeller 组合商品 SKU 数据`);
  } catch (error) {
    ElMessage.warning(error?.message || '生成 BigSeller 组合商品SKU表失败');
  }
}

onMounted(load);
</script>

<style scoped>
.business-page { display: grid; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0 0 8px; }
.page-header p { margin: 0; color: #64748b; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.io-menu-caret { margin-left: 4px; color: #64748b; }
.import-upload-box { display: grid; justify-items: center; gap: 8px; padding: 28px 20px; border: 1px dashed #cbd5e1; border-radius: 8px; background: #fafcff; color: #475569; cursor: pointer; outline: none; }
.import-upload-box:hover, .import-upload-box:focus { border-color: #6366f1; background: #f8f7ff; }
.import-upload-box strong { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.import-upload-box small { color: #94a3b8; text-align: center; }
.import-upload-icon { color: #64748b; font-size: 28px; line-height: 1; }
.import-template-link { margin-top: 8px; }
.components { display: grid; gap: 10px; width: 100%; }
.components > div { display: grid; grid-template-columns: 1fr 130px auto; gap: 10px; }
.summary-alert { margin: 16px 0; }
@media (max-width: 900px) {
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
}
</style>
