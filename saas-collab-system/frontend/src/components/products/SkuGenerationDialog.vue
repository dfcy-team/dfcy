<template>
  <el-dialog
    :model-value="modelValue"
    title="生成 SKU"
    width="min(1320px, 96vw)"
    class="sku-generator-dialog"
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @close="close"
  >
    <div class="sku-generator-heading">
      <strong>{{ target?.spu_code }}&nbsp;&nbsp;{{ target?.product_name }}</strong>
      <el-tag size="small" effect="plain">{{ modeLabel }}</el-tag>
    </div>

    <el-steps :active="step - 1" finish-status="success" align-center class="sku-steps">
      <el-step title="组合设置" />
      <el-step title="组合矩阵" />
      <el-step title="明细预览" />
    </el-steps>

    <section v-if="step === 1" class="step-panel">
      <div class="section-title">选择生成方式</div>
      <el-radio-group v-model="mode" class="mode-grid" data-testid="sku-variant-mode">
        <el-radio-button v-for="item in modes" :key="item.value" :value="item.value">
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>

      <el-form label-position="top" class="selection-form">
        <el-form-item v-if="usesColor" label="颜色" required>
          <el-select
            v-model="selectedColors"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            class="wide-control"
            data-testid="batch-color"
            placeholder="请选择本次需要生成的颜色"
          >
            <el-option
              v-for="color in activeColors"
              :key="color.id || color.code"
              :label="`${color.name}（${color.code}）`"
              :value="String(color.code)"
            />
          </el-select>
        </el-form-item>

        <template v-if="usesSpec">
          <el-alert
            v-if="!dimensions.length"
            title="当前分类未配置规格维度，请先到分类设置中维护规格。"
            type="warning"
            :closable="false"
          />
          <el-form-item v-for="dimension in dimensions" :key="dimension.code" :label="dimension.name || dimension.code" required>
            <el-select
              v-model="selectedSpecs[dimension.code]"
              multiple
              filterable
              allow-create
              default-first-option
              collapse-tags
              collapse-tags-tooltip
              class="wide-control"
              :data-testid="`batch-spec-${dimension.code}`"
              :placeholder="`请选择或填写${dimension.name || dimension.code}`"
            >
              <el-option v-for="value in dimension.values || []" :key="value" :label="value" :value="value" />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
    </section>

    <section v-else-if="step === 2" class="step-panel">
      <div class="matrix-toolbar">
        <div>
          <div class="section-title">选择实际存在的组合</div>
          <div class="muted">默认全选；取消不实际存在的组合后再生成预览。</div>
        </div>
        <div class="matrix-actions">
          <el-button size="small" @click="selectAllCombinations">全选</el-button>
          <el-button size="small" @click="selectedKeys = []">全部取消</el-button>
        </div>
      </div>

      <div class="matrix-wrap" data-testid="sku-combination-matrix">
        <table class="combination-matrix">
          <thead>
            <tr>
              <th>{{ usesColor ? '颜色' : '规格' }}</th>
              <th v-for="spec in matrixSpecAxis" :key="spec.key">{{ specificationText(spec.spec_values) || '无规格' }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="color in matrixColorAxis" :key="color.code || '__no_color__'">
              <th>{{ color.name || '无颜色' }}<small v-if="color.code">{{ color.code }}</small></th>
              <td v-for="spec in matrixSpecAxis" :key="spec.key">
                <el-checkbox
                  :model-value="selectedKeys.includes(combinationKey(color.code, spec.spec_values))"
                  @change="toggleCombination(color.code, spec.spec_values, $event)"
                >生成</el-checkbox>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <el-alert
        v-for="warning in skippedColorWarnings"
        :key="warning"
        :title="warning"
        type="warning"
        :closable="false"
        show-icon
        class="matrix-warning"
      />
      <div class="selection-summary">已选择 {{ selectedKeys.length }} 个组合，单次最多 {{ batchLimit }} 个</div>
    </section>

    <section v-else class="step-panel preview-panel">
      <div class="preview-summary">
        <span>已选择 <b>{{ previewRows.length }}</b> 个组合</span>
        <span class="new-count">新增 {{ newRows.length }}</span>
        <span>已存在 {{ existingRows.length }}（不受影响）</span>
        <el-button size="small" @click="step = 2">返回调整组合</el-button>
        <el-button size="small" @click="extraFieldsVisible = !extraFieldsVisible">
          {{ extraFieldsVisible ? '收起补充字段' : '补充字段' }}
        </el-button>
        <el-button size="small" :disabled="!selectedPreviewRows.length" @click="removeSelectedRows">批量移除</el-button>
      </div>

      <el-table
        ref="previewTable"
        :data="visiblePreviewRows"
        border
        height="470"
        class="preview-table"
        @selection-change="selectedPreviewRows = $event"
      >
        <el-table-column type="selection" width="46" fixed :selectable="(row) => row.status === 'new'" />
        <el-table-column label="状态" width="82" fixed>
          <template #default="{ row }">
            <el-tag :type="row.status === 'new' ? 'success' : 'info'" size="small">
              {{ row.status === 'new' ? '新增' : '已存在' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sku_code" label="SKU 编码" min-width="205" fixed show-overflow-tooltip />
        <el-table-column label="SKU商品名称" min-width="255">
          <template #default="{ row }">
            <div class="name-editor">
              <el-input
                v-model="row.product_name"
                :disabled="row.status !== 'new'"
                maxlength="200"
                @input="markNameSource(row)"
              />
              <el-tag :type="row.name_source === 'manual' ? 'warning' : ''" size="small" effect="plain">
                {{ row.name_source === 'manual' ? '手动' : '自动' }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="图片" min-width="190">
          <template #default="{ row }">
            <div class="image-cell">
              <img v-if="row.image_preview || row.image_url" :src="row.image_preview || row.image_url" alt="SKU图片预览" />
              <div>
                <el-input v-model="row.image_url" :disabled="row.status !== 'new'" size="small" placeholder="粘贴图片URL" />
                <el-upload
                  :auto-upload="false"
                  :show-file-list="false"
                  :disabled="row.status !== 'new'"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  :on-change="(file) => chooseImage(row, file)"
                >
                  <el-button link type="primary" size="small">本地上传</el-button>
                </el-upload>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="重量(g)" width="112"><template #default="{ row }"><el-input-number v-model="row.package_weight" :disabled="row.status !== 'new'" :min="0" :controls="false" /></template></el-table-column>
        <el-table-column label="长(cm)" width="108"><template #default="{ row }"><el-input-number v-model="row.package_length_cm" :disabled="row.status !== 'new'" :min="0" :controls="false" @change="updateVolume(row)" /></template></el-table-column>
        <el-table-column label="宽(cm)" width="108"><template #default="{ row }"><el-input-number v-model="row.package_width_cm" :disabled="row.status !== 'new'" :min="0" :controls="false" @change="updateVolume(row)" /></template></el-table-column>
        <el-table-column label="高(cm)" width="108"><template #default="{ row }"><el-input-number v-model="row.package_height_cm" :disabled="row.status !== 'new'" :min="0" :controls="false" @change="updateVolume(row)" /></template></el-table-column>
        <el-table-column prop="package_volume" label="体积(m³)" width="120" />
        <el-table-column label="采购价(￥)" width="125"><template #default="{ row }"><el-input-number v-model="row.purchase_price" :disabled="row.status !== 'new'" :min="0" :precision="4" :controls="false" /></template></el-table-column>
        <template v-if="extraFieldsVisible">
          <el-table-column label="单位" width="105"><template #default="{ row }"><el-input v-model="row.unit" :disabled="row.status !== 'new'" maxlength="30" /></template></el-table-column>
          <el-table-column label="原产国" width="125"><template #default="{ row }"><el-input v-model="row.origin_country" :disabled="row.status !== 'new'" maxlength="80" /></template></el-table-column>
          <el-table-column label="HS 编码" width="135"><template #default="{ row }"><el-input v-model="row.hs_code" :disabled="row.status !== 'new'" maxlength="20" /></template></el-table-column>
          <el-table-column label="商品描述" min-width="190"><template #default="{ row }"><el-input v-model="row.product_description" :disabled="row.status !== 'new'" maxlength="1000" /></template></el-table-column>
        </template>
        <el-table-column label="操作" width="76" fixed="right">
          <template #default="{ row }"><el-button v-if="row.status === 'new'" link type="danger" @click="row.removed = true">移除</el-button></template>
        </el-table-column>
      </el-table>
      <div class="preview-note">SKU 编码按 SPU－颜色码－规格码生成；仅创建新增项，已有 SKU 不会被覆盖。</div>
    </section>

    <template #footer>
      <el-button :disabled="busy" @click="close">取消</el-button>
      <el-button v-if="step > 1" :disabled="busy" @click="step -= 1">上一步</el-button>
      <el-button v-if="step === 1" type="primary" @click="goToMatrix">下一步</el-button>
      <el-button v-else-if="step === 2" type="primary" :loading="busy" :disabled="!selectedKeys.length" @click="generatePreview">生成预览</el-button>
      <el-button v-else type="primary" :loading="busy" :disabled="!submittableRows.length" data-testid="batch-submit" @click="commit">
        确认生成 {{ submittableRows.length }} 个 SKU
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { bulkCacheProductImages, createProductSkuBatch, uploadProductSkuImage } from '../../api/products';
import { downloadBigSellerProductWorkbook } from '../../utils/bigsellerWorkbook';
import {
  SKU_VARIANT_MODES,
  buildSkuCombinations,
  calculatePackageVolume,
  skuCombinationKey,
} from '../../utils/skuBatch';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  target: { type: Object, default: null },
  colors: { type: Array, default: () => [] },
  dimensions: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:modelValue', 'generated']);

const batchLimit = 200;
const step = ref(1);
const mode = ref(SKU_VARIANT_MODES.COLOR_SPEC);
const selectedColors = ref([]);
const selectedSpecs = reactive({});
const selectedKeys = ref([]);
const previewRows = ref([]);
const selectedPreviewRows = ref([]);
const extraFieldsVisible = ref(false);
const busy = ref(false);
const modes = [
  { value: SKU_VARIANT_MODES.COLOR_SPEC, label: '有颜色有规格' },
  { value: SKU_VARIANT_MODES.COLOR_ONLY, label: '有颜色无规格' },
  { value: SKU_VARIANT_MODES.SPEC_ONLY, label: '无颜色有规格' },
  { value: SKU_VARIANT_MODES.SINGLE, label: '无颜色无规格' },
];

const activeColors = computed(() => props.colors.filter((item) => item?.is_active !== false));
const usesColor = computed(() => [SKU_VARIANT_MODES.COLOR_SPEC, SKU_VARIANT_MODES.COLOR_ONLY].includes(mode.value));
const usesSpec = computed(() => [SKU_VARIANT_MODES.COLOR_SPEC, SKU_VARIANT_MODES.SPEC_ONLY].includes(mode.value));
const modeLabel = computed(() => modes.find((item) => item.value === mode.value)?.label || '生成 SKU');
const allCombinations = computed(() => buildSkuCombinations(mode.value, selectedColors.value, props.dimensions, selectedSpecs));
const combinationKey = (colorCode, specs) => skuCombinationKey(colorCode, specs);
const selectedCombinations = computed(() => allCombinations.value.filter((item) => selectedKeys.value.includes(item.key)));
const matrixSpecAxis = computed(() => {
  const seen = new Map();
  allCombinations.value.forEach((item) => {
    const key = skuCombinationKey('', item.spec_values);
    if (!seen.has(key)) seen.set(key, { key, spec_values: item.spec_values });
  });
  return [...seen.values()];
});
const matrixColorAxis = computed(() => usesColor.value
  ? selectedColors.value.map((code) => ({ code, name: activeColors.value.find((item) => String(item.code) === code)?.name || code }))
  : [{ code: '', name: '无颜色' }]);
const skippedColorWarnings = computed(() => usesColor.value ? matrixColorAxis.value
  .filter((color) => !matrixSpecAxis.value.some((spec) => selectedKeys.value.includes(combinationKey(color.code, spec.spec_values))))
  .map((color) => `${color.name}全部组合已取消，本次将跳过`) : []);
const visiblePreviewRows = computed(() => previewRows.value.filter((row) => !row.removed));
const newRows = computed(() => visiblePreviewRows.value.filter((row) => row.status === 'new'));
const existingRows = computed(() => visiblePreviewRows.value.filter((row) => row.status === 'existing'));
const submittableRows = computed(() => newRows.value);

function reset() {
  step.value = 1;
  mode.value = props.dimensions.length ? SKU_VARIANT_MODES.COLOR_SPEC : SKU_VARIANT_MODES.COLOR_ONLY;
  selectedColors.value = [];
  selectedKeys.value = [];
  previewRows.value = [];
  selectedPreviewRows.value = [];
  extraFieldsVisible.value = false;
  Object.keys(selectedSpecs).forEach((key) => delete selectedSpecs[key]);
  props.dimensions.forEach((dimension) => { selectedSpecs[dimension.code] = []; });
}

watch(() => props.modelValue, (open) => { if (open) reset(); });
function close() { if (!busy.value) emit('update:modelValue', false); }
function specificationText(specs) { return Object.values(specs || {}).filter((value) => value && value !== '0').join('×'); }
function selectAllCombinations() { selectedKeys.value = allCombinations.value.map((item) => item.key); }
function toggleCombination(colorCode, specs, checked) {
  const key = combinationKey(colorCode, specs);
  selectedKeys.value = checked
    ? [...new Set([...selectedKeys.value, key])]
    : selectedKeys.value.filter((item) => item !== key);
}

function goToMatrix() {
  if (usesColor.value && !selectedColors.value.length) return ElMessage.warning('请至少选择一个颜色');
  if (usesSpec.value && (!props.dimensions.length || props.dimensions.some((item) => !(selectedSpecs[item.code] || []).length))) {
    return ElMessage.warning('请为每个规格维度至少选择一个值');
  }
  if (!allCombinations.value.length) return ElMessage.warning('没有可生成的组合');
  if (allCombinations.value.length > batchLimit) return ElMessage.warning(`单次最多生成 ${batchLimit} 个 SKU`);
  selectAllCombinations();
  step.value = 2;
}

function requestBase(items, preview = false) {
  return {
    spu: props.target?.id,
    variant_mode: mode.value,
    color_codes: usesColor.value ? selectedColors.value : [],
    spec_values: usesSpec.value ? Object.fromEntries(props.dimensions.map((item) => [item.code, selectedSpecs[item.code] || []])) : {},
    items,
    preview,
  };
}

async function generatePreview() {
  if (!selectedKeys.value.length || busy.value) return;
  busy.value = true;
  try {
    const response = await createProductSkuBatch(requestBase(selectedCombinations.value, true));
    if (!response.success) return ElMessage.error(response.message || 'SKU 预览生成失败');
    previewRows.value = (response.data?.results || []).map((row) => ({
      ...row,
      auto_name: row.product_name,
      removed: false,
      image_url: row.image_url || '',
      image_file: null,
      image_preview: '',
      package_weight: row.package_weight ?? null,
      package_length_cm: row.package_length_cm ?? null,
      package_width_cm: row.package_width_cm ?? null,
      package_height_cm: row.package_height_cm ?? null,
      package_volume: row.package_volume ?? '',
      purchase_price: row.purchase_price ?? null,
      unit: row.unit || '',
      origin_country: row.origin_country || '',
      hs_code: row.hs_code || '',
      product_description: row.product_description || '',
    }));
    step.value = 3;
  } finally {
    busy.value = false;
  }
}

function markNameSource(row) { row.name_source = row.product_name === row.auto_name ? 'auto' : 'manual'; }
function updateVolume(row) {
  if ([row.package_length_cm, row.package_width_cm, row.package_height_cm].some((value) => value === null || value === '')) {
    row.package_volume = '';
    return;
  }
  row.package_volume = calculatePackageVolume(row.package_length_cm, row.package_width_cm, row.package_height_cm);
}
function chooseImage(row, uploadFile) {
  const raw = uploadFile?.raw;
  if (!raw) return;
  if (row.image_preview?.startsWith('blob:')) URL.revokeObjectURL(row.image_preview);
  row.image_file = raw;
  row.image_preview = URL.createObjectURL(raw);
  row.image_url = '';
}
function removeSelectedRows() {
  selectedPreviewRows.value.forEach((row) => { row.removed = true; });
  selectedPreviewRows.value = [];
}
function detailPayload(row) {
  const fields = ['product_name', 'product_name_source', 'image_url', 'package_weight', 'package_length_cm', 'package_width_cm', 'package_height_cm', 'package_volume', 'purchase_price', 'unit', 'origin_country', 'hs_code', 'product_description'];
  const payload = { sku_code: row.sku_code, color_code: row.color_code, spec_values: row.spec_values };
  row.product_name_source = row.name_source || 'auto';
  fields.forEach((field) => {
    if (row[field] !== '' && row[field] !== null && row[field] !== undefined) payload[field] = row[field];
  });
  return payload;
}

async function commit() {
  if (!submittableRows.value.length || busy.value) return;
  if (submittableRows.value.some((row) => !String(row.product_name || '').trim())) return ElMessage.warning('SKU商品名称不能为空');
  busy.value = true;
  try {
    const rowsToCreate = submittableRows.value;
    const response = await createProductSkuBatch(requestBase(rowsToCreate.map(detailPayload), false));
    if (!response.success) return ElMessage.error(response.message || 'SKU 生成失败');
    const created = response.data?.results || [];
    const uploads = [];
    rowsToCreate.forEach((row) => {
      const createdItem = created.find((item) => item.sku_code === row.sku_code);
      if (row.image_file && createdItem?.id) uploads.push(
        uploadProductSkuImage(createdItem.id, row.image_file).then((result) => {
          if (result?.success && result.data?.image_url) createdItem.image_url = result.data.image_url;
          return result;
        }),
      );
    });
    const remoteImages = rowsToCreate.filter((row) => /^https?:\/\//i.test(row.image_url || ''));
    if (remoteImages.length) uploads.push(
      bulkCacheProductImages({ items: remoteImages.map((row) => ({ sku_code: row.sku_code, image_url: row.image_url })) }).then((result) => {
        (result?.data?.results || []).forEach((item) => {
          const createdItem = created.find((row) => row.sku_code === item.sku_code);
          if (createdItem && (item.cached_url || item.image_url)) createdItem.image_url = item.cached_url || item.image_url;
        });
        return result;
      }),
    );
    const uploadResults = await Promise.allSettled(uploads);
    const imageFailures = uploadResults.filter((item) => item.status === 'rejected' || item.value?.success === false).length;
    let workbookCreated = false;
    try {
      const safeSpu = String(props.target?.spu_code || 'SKU').replace(/[\\/:*?"<>|]/g, '-');
      downloadBigSellerProductWorkbook(created, `BigSeller商品SKU_${safeSpu}.xlsx`);
      workbookCreated = true;
    } catch (error) {
      ElMessage.warning(error?.message || 'BigSeller 商品 SKU 表生成失败');
    }
    emit('generated', response.data || {});
    emit('update:modelValue', false);
    ElMessage.success(`SKU 生成完成：新增 ${response.data?.created || created.length} 个${workbookCreated ? '，已下载 BigSeller 商品 SKU 表' : ''}${imageFailures ? `，${imageFailures} 项图片处理失败` : ''}`);
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.sku-generator-heading,.preview-summary,.matrix-toolbar,.matrix-actions,.name-editor,.image-cell{display:flex;align-items:center;gap:10px}.sku-generator-heading{margin:-4px 0 18px;font-size:16px}.sku-steps{margin:0 40px 26px}.step-panel{min-height:390px}.section-title{font-size:15px;font-weight:700;color:#172033;margin-bottom:8px}.muted,.preview-note{color:#64748b;font-size:13px}.mode-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));width:100%;margin-bottom:24px}.mode-grid :deep(.el-radio-button__inner){width:100%}.selection-form{max-width:880px}.wide-control{width:100%}.matrix-toolbar{justify-content:space-between;margin-bottom:14px}.matrix-wrap{overflow:auto;border:1px solid #dfe6ef;border-radius:6px}.combination-matrix{border-collapse:collapse;min-width:100%;background:#fff}.combination-matrix th,.combination-matrix td{padding:13px 16px;border-right:1px solid #e7ecf2;border-bottom:1px solid #e7ecf2;text-align:center;white-space:nowrap}.combination-matrix th{background:#f7f9fc;color:#344054}.combination-matrix tbody th{text-align:left}.combination-matrix small{display:block;color:#94a3b8;font-weight:400}.matrix-warning{margin-top:10px}.selection-summary{margin-top:14px;color:#475569}.preview-summary{min-height:50px;padding:0 14px;border:1px solid #dfe6ef;border-radius:6px;margin-bottom:10px}.preview-summary .new-count{color:#059669}.preview-summary .el-button:first-of-type{margin-left:auto}.preview-table :deep(.el-input-number){width:100%}.preview-table :deep(.el-table__cell){padding:8px 0}.name-editor{align-items:flex-start}.name-editor .el-tag{margin-top:5px}.image-cell img{width:46px;height:46px;object-fit:cover;border:1px solid #dfe6ef;border-radius:4px}.image-cell>div{min-width:110px}.preview-note{margin-top:12px}.sku-generator-dialog :deep(.el-dialog__body){padding-top:14px}@media(max-width:900px){.mode-grid{grid-template-columns:1fr 1fr}.sku-steps{margin-inline:0}}
</style>
