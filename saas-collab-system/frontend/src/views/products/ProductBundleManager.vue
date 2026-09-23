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
              <el-dropdown-item command="legacy-migration" data-testid="bundle-legacy-migration-button">旧组合关系迁移</el-dropdown-item>
              <el-dropdown-item divided disabled>导出</el-dropdown-item>
              <el-dropdown-item command="bigseller-export" data-testid="bigseller-create-bundle-export" :disabled="!selectedBundles.length || importing || exporting">
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
      title="组合关系按版本和生效时间管理；历史订单保留原快照，不会随当前组合关系变更。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-table :data="bundleRows" row-key="sku_id" border @selection-change="selectBundleRows">
      <el-table-column v-if="canManage" type="selection" width="48" reserve-selection />
      <el-table-column label="图片" width="76">
        <template #default="{ row }">
          <el-image v-if="row.image_url" class="bundle-list-image" :src="row.image_url" fit="cover" preview-teleported :preview-src-list="[row.image_url]" />
          <span v-else class="bundle-list-image-empty">暂无</span>
        </template>
      </el-table-column>
      <el-table-column prop="spu_code" label="组合 SPU" min-width="150">
        <template #default="{ row }">
          <div>{{ row.spu_code }}</div>
          <small v-if="row.legacy_spu_code" class="muted">旧 SPU：{{ row.legacy_spu_code }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="product_name" label="组合商品名称" min-width="220" />
      <el-table-column prop="sku_code" label="组合 SKU" min-width="180" />
      <el-table-column label="当前组成" min-width="260">
        <template #default="{ row }">{{ componentSummary(row.sku_id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openAvailability(row)">库存可用量</el-button>
          <el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑关系</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="visible"
      fullscreen
      append-to-body
      destroy-on-close
      class="bundle-editor-dialog"
      :show-close="false"
      @closed="clearBundleImage"
    >
      <template #header>
        <div class="bundle-editor-header">
          <div class="bundle-editor-title">
            <el-button link aria-label="返回组合商品列表" @click="visible = false">←</el-button>
            <div><strong>添加组合 SKU</strong><small>商品明细数据 / 组合商品</small></div>
          </div>
          <div><el-button @click="visible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></div>
        </div>
      </template>
      <div class="bundle-editor-shell">
        <el-form class="bundle-editor-main" label-position="left" label-width="150px">
          <section id="bundle-basic" class="bundle-section-card">
            <h3>基本信息</h3>
            <el-form-item label="SPU 处理方式" required>
              <el-radio-group v-model="form.spuMode" data-testid="bundle-spu-mode">
                <el-radio value="new">新建组合 SPU</el-radio>
                <el-radio value="existing">选择已有组合 SPU</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="form.spuMode === 'existing'" label="已有组合 SPU" required>
              <div class="full-field">
                <el-select v-model="form.existingSpu" filterable placeholder="搜索新/旧 SPU 编码或商品名称">
                  <el-option v-for="item in activeBundleSpus" :key="item.id" :label="`${item.spu_code} ${item.product_name}${item.legacy_spu_code ? ` · 旧SPU ${item.legacy_spu_code}` : ''}`" :value="item.id" />
                </el-select>
                <div class="field-help">旧 SPU 仅用于搜索与识别，新组合 SKU 将归属当前 SPU。</div>
              </div>
            </el-form-item>
            <el-form-item v-if="form.spuMode === 'new'" label="组合商品名称" required><el-input v-model="form.name" placeholder="请输入组合商品名称" /></el-form-item>
            <el-form-item v-if="form.spuMode === 'new'" label="末级分类" required>
              <el-select v-model="form.category" filterable placeholder="请选择末级分类"><el-option v-for="item in leaves" :key="item.id" :label="`${item.code} ${item.name}`" :value="item.id" /></el-select>
            </el-form-item>
            <el-form-item label="组合商品主图">
              <div class="bundle-image-field">
                <input ref="bundleImageInput" hidden type="file" accept="image/jpeg,image/png,image/gif,image/webp,image/avif" @change="selectBundleImage" />
                <button type="button" class="bundle-image-uploader" @click="bundleImageInput?.click()">
                  <img v-if="bundleImagePreview" :src="bundleImagePreview" alt="组合商品主图预览" />
                  <span v-else><b>＋</b>上传主图</span>
                </button>
                <div class="bundle-image-help">
                  <el-button v-if="bundleImageFile" link type="danger" @click="clearBundleImage">移除</el-button>
                  <p>该图片属于组合 SKU，不会覆盖任何子 SKU 图片。支持 JPG、PNG、GIF、WebP、AVIF，最大 5 MB。</p>
                </div>
              </div>
              <div class="bundle-image-url-row">
                <el-input v-model="bundleImageUrl" clearable placeholder="或粘贴公网图片链接，保存时自动转存本地" @input="clearBundleImageFile" />
                <span>仅允许 HTTP/HTTPS 公网地址；服务端校验图片类型和大小后转存。</span>
              </div>
            </el-form-item>
            <el-form-item label="季节 / 组合颜色">
              <div class="inline-fields">
                <el-select v-model="form.season" placeholder="季节"><el-option v-for="item in options.seasons" :key="item.code" :label="item.name" :value="item.code" /></el-select>
                <el-select v-model="form.color" placeholder="组合颜色"><el-option v-for="item in colors" :key="item.code" :label="`${item.name} (${item.code})`" :value="item.code" /></el-select>
              </div>
            </el-form-item>
          </section>

          <section id="bundle-components" class="bundle-section-card">
            <div class="section-heading"><div><h3>组合信息</h3><p>选择普通商品 SKU，设置每套数量与成本价分摊比，最多 20 项。</p></div><el-button type="primary" plain :disabled="form.components.length >= 20" @click="addFormComponent">+ 选择商品 SKU</el-button></div>
            <div class="component-grid component-grid-head"><span>商品 SKU</span><span>每套数量</span><span>成本价分摊比</span><span>操作</span></div>
            <div v-for="(item, index) in form.components" :key="index" class="component-grid">
              <el-select v-model="item.sku" filterable placeholder="搜索并选择普通 SKU"><el-option v-for="sku in normalSkus" :key="sku.id" :label="sku.sku_code" :value="sku.id" /></el-select>
              <el-input-number v-model="item.quantity" :min="1" />
              <el-input-number v-model="item.costRatio" :min="0.0001" :precision="4" :step="0.1" />
              <el-button link type="danger" :disabled="form.components.length === 1" @click="form.components.splice(index, 1)">删除</el-button>
            </div>
          </section>

          <section id="bundle-version" class="bundle-section-card">
            <h3>版本与生效规则</h3>
            <el-alert title="首次保存生成组合关系 V1。后续修改会创建新版本，已同步订单继续使用原下单快照。" type="info" :closable="false" show-icon />
          </section>
          <section id="bundle-stock" class="bundle-section-card">
            <h3>库存规则</h3>
            <p class="section-note">组合可用量将按各仓最新库存快照，以子 SKU 的最小可组套数量计算；创建组合商品不会直接扣减库存。</p>
          </section>
        </el-form>
        <aside class="bundle-anchor-nav" aria-label="组合商品编辑导航">
          <a href="#bundle-basic">基本信息</a><a href="#bundle-components">组合信息</a><a href="#bundle-version">版本规则</a><a href="#bundle-stock">库存规则</a>
        </aside>
      </div>
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

    <el-dialog v-model="editVisible" title="编辑组合关系" width="min(820px, 96vw)">
      <el-alert title="保存后生成新版本；已同步订单继续使用下单时快照。" type="warning" :closable="false" show-icon />
      <el-form class="phase2-form" label-position="top">
        <el-form-item label="组合 SKU"><el-input :model-value="editForm.skuCode" disabled /></el-form-item>
        <el-form-item label="生效时间" required><el-date-picker v-model="editForm.effectiveAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
        <el-form-item label="变更原因" required><el-input v-model="editForm.reason" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="组成 SKU" required>
          <div class="components">
            <div v-for="(item, index) in editForm.components" :key="index">
              <el-select v-model="item.sku" filterable><el-option v-for="sku in normalSkus" :key="sku.id" :label="sku.sku_code" :value="sku.id" /></el-select>
              <el-input-number v-model="item.quantity" :min="1" />
              <el-input-number v-model="item.costRatio" :min="0.0001" :precision="4" :step="0.1" />
              <el-button @click="editForm.components.splice(index, 1)">删除</el-button>
            </div>
            <el-button :disabled="editForm.components.length >= 20" @click="editForm.components.push({ sku: null, quantity: 1, costRatio: 1 })">添加组成 SKU</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-divider content-position="left">版本记录</el-divider>
      <el-table :data="bundleVersions" border max-height="220">
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="effective_at" label="生效时间" min-width="170" />
        <el-table-column prop="reason" label="变更原因" min-width="200" />
        <el-table-column prop="created_by_name" label="操作人" width="120" />
      </el-table>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存新版本</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="availabilityVisible" title="组合库存可用量" width="min(840px, 96vw)">
      <el-alert title="可用量按各仓最新库存快照与组成数量计算，仅供业务判断，不直接扣减库存。" type="info" :closable="false" show-icon />
      <el-table class="phase2-table" :data="availabilityRows" border v-loading="availabilityLoading">
        <el-table-column prop="warehouse_name" label="仓库" min-width="140" />
        <el-table-column prop="available_quantity" label="组合可用量" width="130" />
        <el-table-column prop="bottleneck_sku_code" label="瓶颈 SKU" min-width="160" />
        <el-table-column prop="snapshot_at" label="库存快照时间" min-width="180" />
      </el-table>
      <template #footer><el-button @click="availabilityVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="migrationVisible" title="旧组合关系迁移" width="min(920px, 96vw)">
      <el-alert title="以文件中的全部组合 SKU 为准，不按 ZH 前缀筛选。确认后仅迁移完整匹配的组合，阻断项不写入并自动生成异常文件。" type="warning" :closable="false" show-icon />
      <input ref="migrationInput" hidden type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="selectMigrationFile" />
      <div class="migration-actions">
        <el-button @click="migrationInput?.click()">选择关系 Excel / CSV</el-button>
        <el-button link type="primary" @click="downloadMigrationTemplate">下载模板</el-button>
        <span>{{ migrationFileName || '尚未选择文件' }}</span>
      </div>
      <el-descriptions v-if="migrationPreview.token" :column="3" border>
        <el-descriptions-item label="待迁移组合">{{ migrationPreview.bundleCount }}</el-descriptions-item>
        <el-descriptions-item label="关系行">{{ migrationPreview.relationCount }}</el-descriptions-item>
        <el-descriptions-item label="阻断错误">{{ migrationPreview.errorCount }}</el-descriptions-item>
        <el-descriptions-item v-if="migrationPreview.errorCount" label="组合 SKU 未找到">{{ migrationPreview.errorBreakdown.bundleNotFound }}</el-descriptions-item>
        <el-descriptions-item v-if="migrationPreview.errorCount" label="组合 SKU 重复匹配">{{ migrationPreview.errorBreakdown.bundleMultiple }}</el-descriptions-item>
        <el-descriptions-item v-if="migrationPreview.errorCount" label="子 SKU 未找到/重复">{{ migrationPreview.errorBreakdown.componentNotFound }} / {{ migrationPreview.errorBreakdown.componentMultiple }}</el-descriptions-item>
      </el-descriptions>
      <el-table v-if="migrationPreview.rows.length" class="phase2-table" :data="migrationPreview.rows" border max-height="260">
        <el-table-column prop="legacy_bundle_spu" label="旧组合 SPU" min-width="140" />
        <el-table-column prop="legacy_bundle_sku" label="旧组合 SKU" min-width="150" />
        <el-table-column prop="legacy_component_sku" label="子 SKU 旧编码" min-width="160" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column label="校验状态" width="110">
          <template #default="{ row }"><el-tag type="success">{{ migrationStatusText(row.status) }}</el-tag></template>
        </el-table-column>
      </el-table>
      <el-table v-if="migrationPreview.errors.length" class="phase2-table" :data="migrationPreview.errors" border max-height="180">
        <el-table-column prop="line" label="行号" width="80" /><el-table-column prop="message" label="阻断原因" />
      </el-table>
      <template #footer>
        <el-button @click="migrationVisible = false">取消</el-button>
        <el-button type="primary" :loading="migrationConfirming" :disabled="!migrationPreview.token || migrationPreview.bundleCount === 0" @click="confirmMigration">
          {{ migrationPreview.errorCount > 0 ? `迁移可用组合（${migrationPreview.bundleCount}）` : '确认迁移' }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import {
  cacheProductBundleImage,
  confirmProductBundleMigration,
  createProductBundle,
  fetchBundleComponents,
  fetchCodingOptions,
  fetchProductBundleAvailability,
  fetchProductBundleDetail,
  fetchProductCategories,
  fetchProductColors,
  fetchProductMasterList,
  fetchProductSkuList,
  previewProductBundleMigration,
  uploadProductSkuImage,
  updateProductBundle,
} from '../../api/products';
import { collectionRows, detailData } from '../../utils/businessResponse';
import { downloadBigSellerBundleWorkbook } from '../../utils/bigsellerWorkbook';

const auth = useAuthStore();
const props = defineProps({
  embedded: { type: Boolean, default: false },
  initialAction: { type: String, default: '' },
});
const canManage = computed(() => auth.hasPermission('products.bundle.manage'));
const spus = ref([]);
const skus = ref([]);
const bundleComponents = ref([]);
const categories = ref([]);
const colors = ref([]);
const options = reactive({ seasons: [] });
const visible = ref(false);
const saving = ref(false);
const bundleImageInput = ref(null);
const bundleImageFile = ref(null);
const bundleImagePreview = ref('');
const bundleImageUrl = ref('');
const importing = ref(false);
const exporting = ref(false);
const bundleImportVisible = ref(false);
const bundleImportInput = ref(null);
const bundleImportUpload = ref(null);
const bundleImportFileName = ref('');
const selectedBundles = ref([]);
const importSummaryVisible = ref(false);
const importSummary = reactive({ fileName: '', created: 0, errors: [] });
const editVisible = ref(false);
const editSaving = ref(false);
const bundleVersions = ref([]);
const editForm = reactive({ skuId: null, skuCode: '', effectiveAt: '', reason: '', components: [] });
const availabilityVisible = ref(false);
const availabilityLoading = ref(false);
const availabilityRows = ref([]);
const migrationVisible = ref(false);
const migrationInput = ref(null);
const migrationFileName = ref('');
const migrationConfirming = ref(false);
const emptyMigrationBreakdown = () => ({ bundleNotFound: 0, bundleMultiple: 0, componentNotFound: 0, componentMultiple: 0 });
const migrationPreview = reactive({ token: '', bundleCount: 0, relationCount: 0, errorCount: 0, errorBreakdown: emptyMigrationBreakdown(), rows: [], errors: [], rejectedRows: [] });
const form = reactive({
  spuMode: 'new', existingSpu: null, name: '', category: null, season: '5', color: null,
  components: [{ sku: null, quantity: 1, costRatio: 1 }],
});

const bundles = computed(() => spus.value.filter((item) => item.product_type === 'bundle'));
const bundleRows = computed(() => bundles.value.flatMap((spu) => skus.value
  .filter((sku) => String(sku.spu) === String(spu.id))
  .map((sku) => ({
    ...spu,
    id: `${spu.id}:${sku.id}`,
    spu_id: spu.id,
    sku_id: sku.id,
    sku_code: sku.sku_code,
    image_url: sku.image_url || spu.image_url || '',
  }))));
const activeBundleSpus = computed(() => bundles.value.filter((item) => item.lifecycle_status !== 'archived'));
const leaves = computed(() => categories.value.filter((item) => item.level === 3 && item.is_active));
const normalSkus = computed(() => {
  const ids = new Set(spus.value.filter((item) => item.product_type !== 'bundle').map((item) => item.id));
  return skus.value.filter((item) => ids.has(item.spu));
});

function bundleSkuCodes(row) {
  return skus.value.filter((item) => String(item.spu) === String(row.id)).map((item) => item.sku_code).join('、');
}

function componentSkuId(component) {
  return component.component_sku_id ?? component.component_sku?.id ?? component.component_sku;
}

function componentSkuCode(component) {
  return component.component_sku_code
    || component.component_sku?.sku_code
    || skus.value.find((item) => String(item.id) === String(componentSkuId(component)))?.sku_code
    || '-';
}

function componentSummary(skuId) {
  const values = bundleComponents.value.filter((item) => String(item.bundle_sku?.id ?? item.bundle_sku) === String(skuId));
  return values.length ? values.map((item) => `${componentSkuCode(item)} × ${item.quantity}`).join('、') : '尚未维护组成关系';
}

function selectBundleRows(rows) {
  const ids = new Set(rows.map((row) => String(row.spu_id)));
  selectedBundles.value = bundles.value.filter((spu) => ids.has(String(spu.id)));
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
  if (form.components.length < 20) form.components.push({ sku: null, quantity: 1, costRatio: 1 });
}

function clearBundleImage() {
  if (bundleImagePreview.value) URL.revokeObjectURL(bundleImagePreview.value);
  bundleImageFile.value = null;
  bundleImagePreview.value = '';
  bundleImageUrl.value = '';
  if (bundleImageInput.value) bundleImageInput.value.value = '';
}

function clearBundleImageFile() {
  if (!bundleImageUrl.value) return;
  if (bundleImagePreview.value) URL.revokeObjectURL(bundleImagePreview.value);
  bundleImageFile.value = null;
  bundleImagePreview.value = '';
  if (bundleImageInput.value) bundleImageInput.value.value = '';
}

function selectBundleImage(event) {
  const file = event.target.files?.[0] || null;
  if (!file) return;
  const allowed = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif']);
  if (!allowed.has(file.type) || file.size <= 0 || file.size > 5 * 1024 * 1024) {
    ElMessage.warning('请选择 5 MB 以内的 JPG、PNG、GIF、WebP 或 AVIF 图片');
    event.target.value = '';
    return;
  }
  if (bundleImagePreview.value) URL.revokeObjectURL(bundleImagePreview.value);
  bundleImageFile.value = file;
  bundleImagePreview.value = URL.createObjectURL(file);
  bundleImageUrl.value = '';
}

async function createBundle({ spuMode = 'new', existingSpu = null, name, category, season, color, components }) {
  const response = await createProductBundle({
    spu_mode: spuMode,
    existing_spu: spuMode === 'existing' ? existingSpu : null,
    product_name: name,
    category_node: category,
    season_code: season,
    color_code: color,
    components: components.map((component) => ({
      component_sku: component.sku,
      quantity: component.quantity,
      cost_allocation_ratio: component.costRatio ?? 1,
    })),
  });
  if (!response.success) throw new Error(response.message || '组合商品原子创建失败');
  const created = detailData(response.data);
  const createdComponents = (created.components || []).map((component, index) => ({
    ...component,
    component_sku_code: component.component_sku_code
      || components[index]?.skuCode
      || normalSkus.value.find((item) => String(item.id) === String(component.component_sku))?.sku_code
      || '',
    cost_allocation_ratio: component.cost_allocation_ratio ?? components[index]?.costRatio ?? 1,
  }));
  return { spu: created.spu, sku: created.sku, components: createdComponents };
}

async function save() {
  if ((form.spuMode === 'new' && (!form.name || !form.category))
    || (form.spuMode === 'existing' && !form.existingSpu)
    || !form.color || !form.components.length || form.components.some((item) => !item.sku || !Number.isFinite(Number(item.costRatio)) || Number(item.costRatio) <= 0)) {
    ElMessage.warning('请完整填写组合商品及组成 SKU');
    return;
  }
  saving.value = true;
  try {
    const result = await createBundle({ ...form, components: form.components });
    let imageUploaded = true;
    if (bundleImageFile.value) {
      try {
        const imageResponse = await uploadProductSkuImage(result.sku.id, bundleImageFile.value);
        imageUploaded = Boolean(imageResponse.success);
      } catch {
        imageUploaded = false;
      }
    } else if (bundleImageUrl.value.trim()) {
      try {
        const imageResponse = await cacheProductBundleImage(result.sku.id, bundleImageUrl.value.trim());
        imageUploaded = Boolean(imageResponse.success && !detailData(imageResponse.data)?.error_count);
      } catch {
        imageUploaded = false;
      }
    }
    visible.value = false;
    if (imageUploaded) ElMessage.success(`组合 SKU ${result.sku.sku_code} 已生成`);
    else ElMessage.warning(`组合 SKU ${result.sku.sku_code} 已生成，但主图上传失败，可稍后在商品明细中补传`);
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
  const rows = Array.isArray(values[0]) ? values : [values];
  const csv = `\ufeff${headers.map(csvCell).join(',')}\n${rows.map((row) => row.map(csvCell).join(',')).join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function migrationStatusText(status) {
  return ({ matched: '匹配成功' })[status] || status || '-';
}

function downloadMigrationErrors(errors) {
  if (!errors.length) return;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
  downloadCsv(
    `旧组合关系迁移异常_${stamp}.csv`,
    ['源文件行号', '旧组合SKU编码', '子SKU旧编码', '数量', '旧组合SPU编码', '错误类型', '阻断原因'],
    errors.map((error) => [error.line, error.legacy_bundle_sku, error.legacy_component_sku, error.quantity, error.legacy_bundle_spu, error.code, error.message])
  );
}

function migrationErrorMessage(error) {
  if (error.message) return error.message;
  if (error.match_reason === 'not_found') return error.code === 'bundle_not_unique' ? '组合 SKU 未找到' : '子 SKU 未找到';
  if (error.match_reason === 'multiple_matches') return `${error.code === 'bundle_not_unique' ? '组合 SKU' : '子 SKU'}匹配到 ${error.match_count} 条商品`;
  return ({
    invalid_row: '组合 SKU、子 SKU 或数量格式不正确',
    bundle_not_unique: '组合 SKU 未找到或匹配到多条商品',
    component_not_unique: '子 SKU 未找到或匹配到多条商品',
    self_or_duplicate: '子 SKU 与组合 SKU 相同或在同一组合内重复',
    nested_bundle_component: '子 SKU 同时也是组合商品，为避免嵌套组合本组合未迁移',
    bundle_contains_blocked_component: '同一组合存在其他阻断的子 SKU，本行未迁移',
  })[error.code] || error.code || '校验失败';
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
  else if (command === 'legacy-migration') openMigration();
  else if (command === 'bigseller-export') exportSelectedBundles();
}

function currentIsoMinute() {
  const date = new Date();
  date.setSeconds(0, 0);
  return date.toISOString();
}

async function openEdit(row) {
  editForm.skuId = row.sku_id;
  editForm.skuCode = row.sku_code;
  editForm.effectiveAt = currentIsoMinute();
  editForm.reason = '';
  editForm.components = [];
  bundleVersions.value = [];
  editVisible.value = true;
  try {
    const response = await fetchProductBundleDetail(row.sku_id);
    if (response.success === false) throw new Error(response.message || '读取组合关系失败');
    const detail = detailData(response.data) || {};
    const current = detail.components || detail.current_components
      || bundleComponents.value.filter((item) => String(item.bundle_sku?.id ?? item.bundle_sku) === String(row.sku_id));
    editForm.components = current.map((item) => ({ sku: componentSkuId(item), quantity: Number(item.quantity || 1), costRatio: Number(item.cost_allocation_ratio ?? 1) }));
    bundleVersions.value = detail.versions || detail.version_history || [];
  } catch (error) {
    ElMessage.error(error?.message || '读取组合关系失败');
  }
}

async function saveEdit() {
  if (!editForm.effectiveAt || !editForm.reason.trim() || !editForm.components.length
    || editForm.components.some((item) => !item.sku || !Number.isInteger(Number(item.quantity)) || !Number.isFinite(Number(item.costRatio)) || Number(item.costRatio) <= 0)) {
    ElMessage.warning('请填写生效时间、变更原因和完整组成 SKU');
    return;
  }
  editSaving.value = true;
  try {
    const response = await updateProductBundle(editForm.skuId, {
      effective_at: editForm.effectiveAt,
      reason: editForm.reason.trim(),
      components: editForm.components.map((item) => ({ component_sku: item.sku, quantity: Number(item.quantity), cost_allocation_ratio: Number(item.costRatio) })),
    });
    if (response.success === false) throw new Error(response.message || '组合关系保存失败');
    editVisible.value = false;
    ElMessage.success('组合关系新版本已保存');
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '组合关系保存失败');
  } finally {
    editSaving.value = false;
  }
}

async function openAvailability(row) {
  availabilityRows.value = [];
  availabilityVisible.value = true;
  availabilityLoading.value = true;
  try {
    const response = await fetchProductBundleAvailability(row.sku_id);
    if (response.success === false) throw new Error(response.message || '库存可用量读取失败');
    const detail = detailData(response.data);
    const rows = Array.isArray(detail) ? detail : (detail?.warehouses || detail?.results || []);
    availabilityRows.value = rows.map((item) => {
      const components = item.components || [];
      const bottleneck = components.reduce((current, component) => (
        current === null || Number(component.bundle_capacity) < Number(current.bundle_capacity) ? component : current
      ), null);
      const snapshotTimes = components.map((component) => component.snapshot_at).filter(Boolean).sort();
      return {
        ...item,
        bottleneck_sku_code: item.bottleneck_sku_code || bottleneck?.component_sku_code || '-',
        snapshot_at: item.snapshot_at || snapshotTimes[0] || '-',
      };
    });
  } catch (error) {
    ElMessage.error(error?.message || '库存可用量读取失败');
  } finally {
    availabilityLoading.value = false;
  }
}

function resetMigrationPreview() {
  Object.assign(migrationPreview, { token: '', bundleCount: 0, relationCount: 0, errorCount: 0, errorBreakdown: emptyMigrationBreakdown(), rows: [], errors: [], rejectedRows: [] });
}

function openMigration() {
  migrationFileName.value = '';
  resetMigrationPreview();
  migrationVisible.value = true;
}

function downloadMigrationTemplate() {
  downloadCsv(
    '旧组合关系迁移模板.csv',
    ['旧组合SKU编码', '子SKU旧编码', '数量', '旧组合SPU编码'],
    ['OLD-BUNDLE-001', 'OLD-SKU-001', 2, '']
  );
}

async function selectMigrationFile(event) {
  const file = event.target.files?.[0] || null;
  event.target.value = '';
  if (!file) return;
  if (!/\.(csv|xlsx)$/i.test(file.name)) { ElMessage.warning('请选择 Excel 或 CSV 文件'); return; }
  migrationFileName.value = file.name;
  resetMigrationPreview();
  try {
    const payload = new FormData();
    payload.append('file', file);
    const response = await previewProductBundleMigration(payload);
    if (response.success === false) throw new Error(response.message || '迁移预览失败');
    const preview = detailData(response.data) || {};
    const previewRows = preview.rows || preview.items || [];
    const breakdown = preview.error_breakdown || {};
    Object.assign(migrationPreview, {
      token: preview.token || preview.preview_token || '',
      bundleCount: preview.bundle_count ?? preview.bundles_ready ?? 0,
      relationCount: preview.input_rows ?? previewRows.length,
      errorCount: preview.error_count ?? (preview.errors || []).length,
      errorBreakdown: {
        bundleNotFound: breakdown['bundle_not_unique:not_found'] || 0,
        bundleMultiple: breakdown['bundle_not_unique:multiple_matches'] || 0,
        componentNotFound: breakdown['component_not_unique:not_found'] || 0,
        componentMultiple: breakdown['component_not_unique:multiple_matches'] || 0,
      },
      rows: previewRows,
      errors: (preview.errors || []).map((error) => ({
        ...error,
        line: error.line ?? error.row ?? '-',
        message: migrationErrorMessage(error),
      })),
      rejectedRows: (preview.rejected_rows || []).map((error) => ({ ...error, message: migrationErrorMessage(error) })),
    });
    if (!migrationPreview.token) throw new Error('服务端未返回迁移确认令牌');
  } catch (error) {
    resetMigrationPreview();
    migrationPreview.errorCount = 1;
    migrationPreview.errors = [{ line: '-', message: error?.message || '迁移预览失败' }];
    ElMessage.error(error?.message || '迁移预览失败');
  }
}

async function confirmMigration() {
  migrationConfirming.value = true;
  try {
    const response = await confirmProductBundleMigration(migrationPreview.token);
    if (response.success === false) throw new Error(response.message || '迁移确认失败');
    const result = detailData(response.data) || {};
    const migrated = result.migrated ?? result.bundle_count ?? result.bundles_ready ?? migrationPreview.bundleCount;
    const skipped = result.skipped_errors ?? result.error_count ?? migrationPreview.errorCount;
    if (skipped > 0) downloadMigrationErrors(migrationPreview.rejectedRows);
    ElMessage.success(skipped > 0
      ? `已迁移 ${migrated} 个匹配组合，${skipped} 条异常未写入，已生成异常文件`
      : `旧组合关系迁移完成，共处理 ${migrated} 个组合`);
    migrationVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '迁移确认失败');
  } finally {
    migrationConfirming.value = false;
  }
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
    if (!Number.isFinite(costRatio) || costRatio <= 0) throw new Error(`SKU${index}成本价分摊比必须大于 0`);
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

async function exportSelectedBundles() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const selectedSkus = [];
    for (const spu of selectedBundles.value) {
      for (let page = 1; ; page += 1) {
        const response = await fetchProductSkuList({ spu_id: spu.id, page, page_size: 100 });
        if (!response.success) throw new Error(response.message || '读取组合 SKU 失败');
        const rows = collectionRows(response.data);
        selectedSkus.push(...rows);
        if (rows.length < 100) break;
      }
    }
    if (!selectedSkus.length) throw new Error('所选组合商品没有 SKU');
    const relations = [];
    for (const sku of selectedSkus) {
      const response = await fetchProductBundleDetail(sku.id);
      if (!response.success) throw new Error(response.message || `读取组合 SKU ${sku.sku_code} 成分失败`);
      const components = detailData(response.data)?.components || [];
      if (!components.length || components.some((item) => !item.component_sku_code)) {
        throw new Error(`组合 SKU ${sku.sku_code} 缺少完整成分信息，无法导出`);
      }
      relations.push(...components.map((item) => ({ ...item, bundle_sku: sku.id })));
    }
    const count = downloadBigSellerBundleWorkbook(selectedBundles.value, selectedSkus, relations);
    ElMessage.success(`已生成 ${count} 条 BigSeller 组合商品 SKU 数据`);
  } catch (error) {
    ElMessage.warning(error?.message || '生成 BigSeller 组合商品SKU表失败');
  } finally {
    exporting.value = false;
  }
}

onMounted(async () => {
  await load();
  if (props.initialAction === 'create') visible.value = true;
  if (props.initialAction === 'import') openBundleImport();
  if (props.initialAction === 'legacy-migration') openMigration();
});
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
.components > div { display: grid; grid-template-columns: 1fr 130px 150px auto; gap: 10px; }
.field-help { margin-top: 6px; color: #64748b; font-size: 12px; }
.summary-alert { margin: 16px 0; }
.muted { color: #94a3b8; }
.bundle-list-image { width: 44px; height: 44px; border: 1px solid #dbe3ec; border-radius: 6px; background: #f8fafc; }
.bundle-list-image-empty { color: #94a3b8; font-size: 12px; }
.phase2-form, .phase2-table { margin-top: 16px; }
.migration-actions { display: flex; align-items: center; gap: 10px; margin: 16px 0; color: #64748b; }
:deep(.bundle-editor-dialog) { background: #f4f5f7; }
:deep(.bundle-editor-dialog .el-dialog__header) { margin: 0; padding: 0; position: sticky; top: 0; z-index: 8; }
:deep(.bundle-editor-dialog .el-dialog__body) { padding: 0; }
.bundle-editor-header { min-height: 60px; padding: 0 26px; display: flex; align-items: center; justify-content: space-between; gap: 16px; background: #fff; border-bottom: 1px solid #e5e7eb; box-shadow: 0 2px 8px rgb(15 23 42 / 6%); }
.bundle-editor-title { display: flex; align-items: center; gap: 10px; }
.bundle-editor-title strong { display: block; color: #1f2937; font-size: 16px; }
.bundle-editor-title small { display: block; margin-top: 2px; color: #94a3b8; font-size: 12px; }
.bundle-editor-shell { width: min(1180px, calc(100vw - 48px)); margin: 20px auto 48px; display: grid; grid-template-columns: minmax(0, 1fr) 140px; gap: 18px; align-items: start; }
.bundle-editor-main { display: grid; gap: 16px; }
.bundle-section-card { padding: 22px 24px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; scroll-margin-top: 76px; }
.bundle-section-card h3 { margin: 0 0 22px; color: #273142; font-size: 16px; }
.bundle-section-card :deep(.el-form-item:last-child) { margin-bottom: 0; }
.bundle-section-card :deep(.el-input), .bundle-section-card :deep(.el-select) { width: 100%; }
.full-field { width: 100%; }
.inline-fields { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.bundle-image-field { width: 100%; display: flex; align-items: center; gap: 14px; }
.bundle-image-uploader { width: 112px; height: 112px; flex: 0 0 112px; padding: 0; overflow: hidden; border: 1px dashed #cbd5e1; border-radius: 6px; background: #fafcff; color: #64748b; cursor: pointer; }
.bundle-image-uploader:hover { border-color: #409eff; color: #409eff; }
.bundle-image-uploader img { width: 100%; height: 100%; object-fit: cover; display: block; }
.bundle-image-uploader span { display: grid; place-items: center; gap: 5px; font-size: 13px; }
.bundle-image-uploader b { font-size: 24px; font-weight: 400; line-height: 1; }
.bundle-image-help p { max-width: 480px; margin: 6px 0 0; color: #94a3b8; font-size: 12px; line-height: 1.6; }
.bundle-image-url-row { width: 100%; margin-top: 12px; }
.bundle-image-url-row span { display: block; margin-top: 6px; color: #94a3b8; font-size: 12px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.section-heading h3 { margin-bottom: 5px; }
.section-heading p, .section-note { margin: 0; color: #64748b; line-height: 1.7; }
.component-grid { display: grid; grid-template-columns: minmax(0, 1fr) 130px 150px 70px; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid #ebeef5; border-top: 0; }
.component-grid-head { padding: 9px 12px; border-top: 1px solid #ebeef5; background: #f8fafc; color: #64748b; font-size: 12px; font-weight: 600; }
.bundle-anchor-nav { position: sticky; top: 82px; padding: 4px 0; border-left: 1px solid #d8dee9; display: grid; gap: 2px; }
.bundle-anchor-nav a { position: relative; padding: 9px 16px; color: #64748b; text-decoration: none; font-size: 13px; }
.bundle-anchor-nav a::before { content: ''; position: absolute; left: -4px; top: 16px; width: 7px; height: 7px; border-radius: 50%; background: #8b5cf6; }
.bundle-anchor-nav a:hover { color: #5b21b6; background: #f5f3ff; }
@media (max-width: 900px) {
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .bundle-editor-shell { width: calc(100vw - 24px); grid-template-columns: 1fr; }
  .bundle-anchor-nav { display: none; }
  .inline-fields { grid-template-columns: 1fr; }
  .component-grid { grid-template-columns: minmax(0, 1fr) 110px 130px 54px; }
}
</style>
