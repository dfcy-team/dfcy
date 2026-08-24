<template>
  <AppPage
    eyebrow="MASTER DATA"
    title="平台商品明细"
    subtitle="按平台、店铺维护商品与变体快照；旧 SKU 关联仅用于内部 SKU 映射，不保存平台凭据。"
    boundary-note="页面只展示当前 tenant 可见的商品明细；导入会校验平台、店铺、国家代码和旧 SKU 的租户边界。"
    :capability="capability"
  >
    <template #action>
      <el-button class="template-button" @click="downloadTemplate">下载导入模板</el-button>
      <el-button class="format-button" @click="templateDialog = true">字段说明</el-button>
      <el-button class="import-button" type="primary" :loading="importing" :disabled="importing" @click="fileInput?.click()">{{ importing ? '正在导入' : '导入 CSV/XLSX' }}</el-button>
      <el-button class="variant-id-import-button" :loading="importing" :disabled="importing" @click="variantProductIdFileInput?.click()">按变体ID导入平台商品ID</el-button>
      <input ref="fileInput" hidden type="file" accept=".csv,.xlsx" @change="onImport" />
      <input ref="variantProductIdFileInput" hidden type="file" accept=".csv,.xlsx" @change="onVariantProductIdImport" />
    </template>

    <el-alert
      v-if="message"
      class="page-message"
      :title="message"
      :type="messageType"
      show-icon
      closable
      @close="message = ''"
    />

    <div class="detail-workspace">
      <aside class="category-panel">
        <div class="panel-title">
          <strong>分类目录</strong>
          <el-button link @click="selectCategory(null)">全部</el-button>
        </div>
        <el-input v-model="categorySearch" clearable placeholder="搜索分类" @input="categoryTreeRef?.filter(categorySearch)" />
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
      <main class="detail-content">
    <section class="resource-summary" aria-label="数据摘要">
      <div class="summary-item">
        <span>当前结果</span>
        <strong>{{ total }}</strong>
      </div>
      <div class="summary-item">
        <span>已关联新 SKU</span>
        <strong>{{ linkedCount }}</strong>
      </div>
      <div class="summary-item">
        <span>在售明细</span>
        <strong>{{ onSaleCount }}</strong>
      </div>
      <div class="summary-item summary-item--scope">
        <span>数据边界</span>
        <strong>当前 tenant</strong>
      </div>
    </section>

    <section class="resource-toolbar" aria-label="筛选条件">
      <el-input
        v-model="filters.search"
        clearable
        placeholder="搜索标题、平台 SKU 或旧 SKU"
        @keyup.enter="submitFilters"
      />
      <el-select v-model="filters.platform_id" clearable filterable placeholder="全部平台" @change="resetPage">
        <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.store_id" clearable filterable placeholder="全部店铺" @change="resetPage">
        <el-option v-for="item in storeOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.sales_status" clearable placeholder="全部销售状态" @change="resetPage">
        <el-option label="在售" value="在售" />
        <el-option label="停售" value="停售" />
        <el-option label="草稿" value="草稿" />
      </el-select>
      <div class="toolbar-actions">
        <el-button type="primary" @click="submitFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button v-if="canManage" @click="openBulk">批量修改</el-button>
      </div>
    </section>

    <AppState
      v-if="pageState !== 'ready' && pageState !== 'empty'"
      :status="pageState"
      :title="stateTitle"
      :detail="stateDetail"
      @action="loadData"
    />

    <section v-else class="resource-table" aria-label="平台商品明细列表">
      <el-table :data="rows" row-key="id" border table-layout="fixed" empty-text="暂无符合条件的平台商品明细" @selection-change="selectedRows = $event">
        <el-table-column type="index" label="序号" width="70" :index="(filters.page - 1) * filters.page_size + 1" />
        <el-table-column v-if="canManage" type="selection" width="48" reserve-selection />
        <el-table-column prop="platform_name" label="平台" min-width="130" show-overflow-tooltip />
        <el-table-column prop="country_code" label="国家代码" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.country_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="store_name" label="店铺" min-width="140" show-overflow-tooltip />
        <el-table-column prop="platform_product_id" label="平台商品 ID" min-width="150" show-overflow-tooltip />
        <el-table-column prop="platform_variant_id" label="变体 ID" min-width="140" show-overflow-tooltip />
        <el-table-column prop="platform_sku" label="平台 SKU" min-width="140" show-overflow-tooltip />
        <el-table-column prop="source_old_sku_code" label="旧 SKU 关联" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_old_sku_code || row.internal_legacy_sku_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="internal_sku_code" label="新 SKU" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.internal_sku_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="190" show-overflow-tooltip />
        <el-table-column prop="variant" label="变体" min-width="150" show-overflow-tooltip />
        <el-table-column prop="sales_status" label="销售状态" min-width="110">
          <template #default="{ row }">
            <el-tag :type="salesStatusType(row.sales_status)" effect="plain">
              {{ row.sales_status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="负责人" min-width="110" show-overflow-tooltip />
        <el-table-column prop="leader" label="组长" min-width="110" show-overflow-tooltip />
        <el-table-column v-if="canManage" label="操作" min-width="110" fixed="right">
          <template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button></template>
        </el-table-column>
      </el-table>

      <footer class="resource-pagination">
        <span>共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.page_size"
          :page-sizes="pageSizeOptions"
          :total="total"
          layout="sizes, prev, pager, next, jumper"
          @size-change="handlePageSizeChange"
          @current-change="handlePageChange"
        />
      </footer>
    </section>
      </main>
    </div>

    <el-dialog v-model="importDialog" :title="importing ? '正在导入' : '导入结果'" width="min(680px, 94vw)" :close-on-click-modal="!importing" :show-close="!importing">
      <el-steps :active="importStep" finish-status="success" align-center><el-step title="文件已选择"/><el-step title="上传并解析"/><el-step title="导入完成"/></el-steps>
      <div class="import-status" v-loading="importing">
        <p><strong>{{ importStatus }}</strong></p>
        <p class="import-meta">文件：{{ importFileName || '-' }} · 已用时 {{ importElapsedSeconds }} 秒</p>
        <div
          v-if="importResult"
          class="import-result-panel"
          :class="{ 'import-result-panel--warning': importHasWarnings }"
        >
          <div class="import-summary-grid" aria-label="导入汇总">
            <div class="import-summary-item"><span>处理行数</span><strong>{{ importSummary.total }}</strong></div>
            <div class="import-summary-item"><span>新增</span><strong>{{ importSummary.created }}</strong></div>
            <div class="import-summary-item"><span>更新</span><strong>{{ importSummary.updated }}</strong></div>
            <div class="import-summary-item"><span>无变化</span><strong>{{ importSummary.unchanged }}</strong></div>
            <div class="import-summary-item"><span>未匹配</span><strong>{{ importSummary.unmatched }}</strong></div>
            <div class="import-summary-item"><span>跳过</span><strong>{{ importSummary.skipped }}</strong></div>
          </div>
          <p v-if="importMode === 'variant_product_id' && importSummary.unmatched" class="import-warning">
            当前租户平台商品明细中不存在，已跳过 {{ importSummary.unmatched }} 条。
            <span v-if="importSummary.unmatchedSample.length">示例变体ID：{{ importSummary.unmatchedSample.join('、') }}。</span>
            <span v-if="importSummary.unmatchedRemaining">另有 {{ importSummary.unmatchedRemaining }} 个未匹配变体ID未展开。</span>
          </p>
          <p v-if="importMode === 'variant_product_id' && importSummary.ambiguous" class="import-warning">
            有 {{ importSummary.ambiguous }} 条变体ID在当前租户内对应多个平台/店铺记录，无法确定更新对象，已跳过。
          </p>
          <div v-if="importSummary.errors.length" class="import-errors">
            <p>有 {{ importSummary.errors.length }} 条数据未通过校验：</p>
            <ul>
              <li v-for="(error, index) in importSummary.errors.slice(0, 5)" :key="`${error.row || 'error'}-${index}`">{{ formatImportError(error) }}</li>
            </ul>
            <p v-if="importSummary.errors.length > 5" class="import-meta">其余 {{ importSummary.errors.length - 5 }} 条错误已折叠。</p>
          </div>
          <p v-if="!importHasWarnings && importSummary.total" class="import-success">全部数据已处理完成。</p>
        </div>
      </div>
      <template #footer><el-button :disabled="importing" @click="importDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="templateDialog" title="导入模板与字段说明" width="min(920px, 94vw)">
      <p class="template-help">
        请先下载 CSV 模板并按首行字段填写；系统同时接受 Excel 另存的 XLSX 文件。必填字段为空、平台/店铺/国家代码不属于当前租户，或旧 SKU 无法匹配时，该行会被拒绝且不会写入其他行。
      </p>
      <el-table :data="importFields" border size="small" class="template-fields">
        <el-table-column prop="field" label="字段" min-width="140" />
        <el-table-column prop="required" label="必填" width="70" />
        <el-table-column prop="description" label="填写说明" min-width="360" show-overflow-tooltip />
        <el-table-column prop="example" label="示例" min-width="150" show-overflow-tooltip />
      </el-table>
      <el-divider content-position="left">按变体ID导入平台商品ID</el-divider>
      <p class="template-help">该模式只更新已有明细的“平台商品ID”，文件必须包含“变体ID”和“平台商品ID”两列。系统按当前租户匹配；同一变体ID对应多个平台/店铺时会报冲突并跳过，平台商品ID允许多个变体共用。</p>
      <el-table :data="variantProductIdImportFields" border size="small" class="template-fields">
        <el-table-column prop="field" label="字段" min-width="160" />
        <el-table-column prop="required" label="必填" width="70" />
        <el-table-column prop="description" label="填写说明" min-width="420" />
        <el-table-column prop="example" label="示例" min-width="160" />
      </el-table>
      <template #footer>
        <el-button @click="templateDialog = false">关闭</el-button>
        <el-button @click="downloadVariantProductIdTemplate">下载变体ID模板</el-button>
        <el-button type="primary" @click="downloadTemplate">再次下载 CSV 模板</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑平台商品明细" width="min(620px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="editForm.title" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="变体标题"><el-input v-model="editForm.variant" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="平台商品 ID"><el-input v-model="editForm.platform_product_id" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="平台变体 ID"><el-input v-model="editForm.platform_variant_id" placeholder="留空则不修改，必须保持店铺内唯一" /></el-form-item>
        <el-form-item label="平台 SKU"><el-input v-model="editForm.platform_sku" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="销售状态"><el-input v-model="editForm.sales_status" placeholder="例如：在售、停售、草稿" /></el-form-item>
        <el-form-item label="负责人"><el-input v-model="editForm.owner" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="组长"><el-input v-model="editForm.leader" placeholder="留空则不修改" /></el-form-item>
        <el-form-item label="旧 SKU 关联"><el-input v-model="editForm.source_old_sku_code" placeholder="留空则不修改，必须匹配已存在 SKU" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bulkVisible" title="按 SPU 批量修改平台商品明细" width="min(640px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="匹配类型" required>
          <el-radio-group v-model="bulkForm.match_type">
            <el-radio value="old_spu">旧 SPU 编码</el-radio>
            <el-radio value="new_spu">新 SPU 编码</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="精确 SPU 编码" required><el-input v-model="bulkForm.spu_code" placeholder="请输入完整 SPU 编码" @keyup.enter="previewBulk" /></el-form-item>
        <el-form-item label="批量修改字段">
          <el-input v-model="bulkForm.title" placeholder="标题（留空不覆盖）" />
          <el-input v-model="bulkForm.variant" class="bulk-field" placeholder="变体标题（留空不覆盖）" />
          <el-input v-model="bulkForm.sales_status" class="bulk-field" placeholder="销售状态（留空不覆盖）" />
          <el-input v-model="bulkForm.owner" class="bulk-field" placeholder="负责人（留空不覆盖）" />
          <el-input v-model="bulkForm.leader" class="bulk-field" placeholder="组长（留空不覆盖）" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="bulkPreview !== null"
        :title="selectedRows.length ? `当前条件匹配 ${bulkPreview} 条，将修改已选择的 ${selectedRows.length} 条` : `当前条件匹配 ${bulkPreview} 条，未选择记录，将修改全部匹配记录（含其他分页）`"
        type="info"
        :closable="false"
      />
      <template #footer>
        <el-button :disabled="bulkSaving" @click="previewBulk">预览匹配数量</el-button>
        <el-button @click="bulkVisible = false">取消</el-button>
        <el-button type="primary" :loading="bulkSaving" @click="saveBulk">确认修改</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPlatforms, fetchStores } from '../../api/masterData';
import { fetchPlatformProductDetails, importPlatformProductDetails, importPlatformProductIds, updatePlatformProductDetail, bulkUpdatePlatformProductDetails } from '../../api/platformProductDetails';
import { fetchProductCategories } from '../../api/products';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { statusFromApiResponse } from '../../utils/uiState';

const fileInput = ref(null);
const variantProductIdFileInput = ref(null);
const rows = ref([]);
const allRows = ref([]);
const total = ref(0);
const loading = ref(false);
const pageState = ref('loading');
const stateTitle = ref('');
const stateDetail = ref('');
const capability = ref(useMock ? 'mock' : 'pending');
const message = ref('');
const messageType = ref('success');
const importDialog = ref(false);
const templateDialog = ref(false);
const importResult = ref(null);
const importMode = ref('full');
const importing = ref(false), importStep = ref(0), importStatus = ref('等待选择文件'), importFileName = ref(''), importElapsedSeconds = ref(0);
let importTimer = null;
const serverPaginated = ref(false);
const platformOptions = ref([]);
const storeOptions = ref([]);
const filters = reactive({ search: '', platform_id: '', store_id: '', sales_status: '', category_id: '', page: 1, page_size: 20 });
const pageSizeOptions = [20, 50, 100];
const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('listings.product_detail.manage'));
const categories = ref([]);
const categorySearch = ref('');
const categoryTreeRef = ref(null);
const selectedRows = ref([]);
const editVisible = ref(false);
const editSaving = ref(false);
const editForm = reactive({ id: null, title: '', variant: '', platform_product_id: '', platform_variant_id: '', platform_sku: '', sales_status: '', owner: '', leader: '', source_old_sku_code: '' });
const bulkVisible = ref(false);
const bulkSaving = ref(false);
const bulkPreview = ref(null);
const bulkForm = reactive({ match_type: 'old_spu', spu_code: '', title: '', variant: '', sales_status: '', owner: '', leader: '' });

function importCount(value) {
  const count = Number(value);
  return Number.isFinite(count) && count >= 0 ? count : 0;
}

const importSummary = computed(() => {
  const value = importResult.value;
  const data = value?.data && typeof value.data === 'object' && !Array.isArray(value.data) && !('total' in value)
    ? value.data
    : value;
  const result = data && typeof data === 'object' && !Array.isArray(data) ? data : {};
  return {
    total: importCount(result.total),
    created: importCount(result.created),
    updated: importCount(result.updated),
    unchanged: importCount(result.unchanged),
    unmatched: importCount(result.unmatched),
    ambiguous: importCount(result.ambiguous),
    skipped: importCount(result.skipped),
    unmatchedSample: Array.isArray(result.unmatched_sample) ? result.unmatched_sample.map((item) => String(item)) : [],
    unmatchedRemaining: importCount(result.unmatched_remaining),
    errors: Array.isArray(result.errors) ? result.errors : [],
  };
});

const importHasWarnings = computed(() => Boolean(
  importSummary.value.unmatched
    || importSummary.value.ambiguous
    || importSummary.value.skipped
    || importSummary.value.errors.length,
));

function formatImportError(error) {
  const row = error?.row ? `第 ${error.row} 行：` : '';
  return `${row}${error?.message || error?.code || '字段校验未通过'}`;
}

const categoryTree = computed(() => {
  const map = new Map(categories.value.map((item) => [item.id, { ...item, displayName: `${item.code || ''} ${item.name || ''}`.trim(), children: [] }]));
  const roots = [];
  for (const node of map.values()) {
    const parent = map.get(node.parent);
    if (parent) parent.children.push(node); else roots.push(node);
  }
  return roots;
});

const importFields = [
  { field: '平台', required: '是', description: '平台编码、名称或平台类型；必须属于当前租户。', example: 'tiktok' },
  { field: '店铺', required: '是', description: '店铺编码或名称；必须属于所选平台和当前租户。', example: 'shop-th' },
  { field: '国家代码', required: '否', description: 'CountrySiteMaster.country_code（如 TH）；填写时必须与店铺国家一致，并匹配当前租户的国家档案。', example: 'TH' },
  { field: '平台商品ID', required: '否', description: '平台商品（SPU）标识。', example: 'P-1001' },
  { field: '变体ID', required: '是', description: '平台变体标识；同一租户的平台+店铺内用于幂等更新。', example: 'V-1001' },
  { field: '平台SKU', required: '否', description: '平台侧 SKU 标识。', example: 'TSHIRT-BLACK-M' },
  { field: '旧SKU编码', required: '二选一', description: '与新SKU编码至少填写一个；用于匹配旧 SKU 迁移关系。', example: 'OLD-SKU-001' },
  { field: '新SKU编码', required: '二选一', description: '与旧SKU编码至少填写一个；两者都填时优先使用新 SKU。', example: '101010004-blue' },
  { field: '标题', required: '否', description: '平台商品标题。', example: 'Basic T-shirt' },
  { field: '变体', required: '否', description: '颜色、尺码等变体描述。', example: 'Black / M' },
  { field: 'L1类目 / L2类目 / L3类目', required: '否', description: '平台类目层级，可留空。', example: '服饰 / 上衣 / T恤' },
  { field: 'SKU前缀', required: '否', description: '内部业务使用的 SKU 前缀。', example: 'APP' },
  { field: '销售状态', required: '否', description: '在售、停售、草稿等状态文本。', example: '在售' },
  { field: '负责人 / 组长', required: '否', description: '店铺负责人及组长文本。', example: '张三 / 李四' },
  { field: '平台创建时间 / 平台更新时间', required: '否', description: '支持 ISO 或 YYYY-MM-DD[ HH:mm:ss] 格式。', example: '2026-08-13 10:00:00' },
];
const variantProductIdImportFields = [
  { field: '变体ID', required: '是', description: '平台变体标识；必须能在当前租户内唯一匹配一条平台商品明细。', example: 'V-1001' },
  { field: '平台商品ID', required: '是', description: '平台商品（SPU）标识；允许多个变体使用同一个平台商品ID。', example: 'P-1001' },
];

const templateHeaders = [
  '平台', '店铺', '国家代码', '平台商品ID', '变体ID', '平台SKU', '旧SKU编码', '新SKU编码', '标题', '变体',
  'L1类目', 'L2类目', 'L3类目', 'SKU前缀', '销售状态', '负责人', '组长', '平台创建时间', '平台更新时间',
];
const templateExample = [
  'tiktok', 'shop-th', 'TH', 'P-1001', 'V-1001', 'TSHIRT-BLACK-M', '', '101010004-blue',
  'Basic T-shirt', 'Black / M', '服饰', '上衣', 'T恤', 'APP', '在售', '张三', '李四', '2026-08-13 10:00:00', '2026-08-13 10:00:00',
];

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadTemplate() {
  const csv = `\ufeff${templateHeaders.map(csvCell).join(',')}\r\n${templateExample.map(csvCell).join(',')}\r\n`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '平台商品明细导入模板.csv';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const linkedCount = computed(() => allRows.value.filter((row) => row.internal_sku_code || row.internal_sku).length);
const onSaleCount = computed(() => allRows.value.filter((row) => /active|on.?sale|在售/i.test(String(row.sales_status || ''))).length);

function responseRows(response) {
  const data = response?.data;
  if (Array.isArray(data)) return { results: data, count: data.length, paginated: false, apiStatus: response?.api_status };
  const results = Array.isArray(data?.results) ? data.results : (Array.isArray(data?.items) ? data.items : []);
  return {
    results,
    count: Number.isFinite(Number(data?.count)) ? Number(data.count) : results.length,
    paginated: Array.isArray(data?.results) && ('next' in data || 'previous' in data),
    apiStatus: data?.api_status || response?.api_status,
  };
}

function applyRows(results) {
  allRows.value = results;
  if (serverPaginated.value) rows.value = results;
  else {
    const start = (filters.page - 1) * filters.page_size;
    rows.value = results.slice(start, start + filters.page_size);
  }
}

function filterCategory(value, data) {
  if (!value) return true;
  return String(data.displayName || data.name || '').toLowerCase().includes(String(value).toLowerCase());
}

function selectCategory(data) {
  filters.category_id = data?.id ? String(data.id) : '';
  filters.page = 1;
  loadData();
}

async function loadData({ retryOutOfRange = true } = {}) {
  loading.value = true;
  pageState.value = 'loading';
  stateTitle.value = '';
  stateDetail.value = '';
  const response = await fetchPlatformProductDetails({ ...filters, status: filters.sales_status });
  if (!response?.success) {
    // The backend returns 404 when a page falls beyond the current result set
    // (for example after a filter/import changed the total). Re-run once from
    // the first page so users never remain on an empty invalid page.
    if (retryOutOfRange && filters.page > 1 && Number(response?.http_status) === 404) {
      filters.page = 1;
      await loadData({ retryOutOfRange: false });
      return;
    }
    loading.value = false;
    pageState.value = statusFromApiResponse(response, typeof navigator === 'undefined' ? true : navigator.onLine);
    stateTitle.value = '平台商品明细加载失败';
    stateDetail.value = response?.message || '接口请求失败';
    capability.value = response?.http_status ? 'pending' : 'degraded';
    return;
  }
  loading.value = false;
  const payload = responseRows(response);
  // A successful response can still reveal that the requested page is now
  // beyond the last page (for example after concurrent imports/deletions).
  // Use the count from this response to jump to the last valid page once.
  const lastPage = Math.max(1, Math.ceil(payload.count / filters.page_size));
  if (retryOutOfRange && payload.count > 0 && filters.page > lastPage) {
    filters.page = lastPage;
    await loadData({ retryOutOfRange: false });
    return;
  }
  serverPaginated.value = payload.paginated;
  total.value = payload.count;
  applyRows(payload.results);
  capability.value = payload.apiStatus || (useMock ? 'mock' : 'connected');
  pageState.value = payload.results.length ? 'ready' : 'empty';
}

function handlePageChange(page) {
  filters.page = Math.max(1, Number(page) || 1);
  if (serverPaginated.value) loadData();
  else applyRows(allRows.value);
}

function handlePageSizeChange(size) {
  const parsed = Number(size);
  filters.page_size = pageSizeOptions.includes(parsed) ? parsed : pageSizeOptions[0];
  filters.page = 1;
  if (serverPaginated.value) loadData();
  else applyRows(allRows.value);
}

function resetPage() {
  filters.page = 1;
}

function submitFilters() {
  filters.page = 1;
  loadData();
}

function resetFilters() {
  filters.search = '';
  filters.platform_id = '';
  filters.store_id = '';
  filters.sales_status = '';
  filters.category_id = '';
  filters.page = 1;
  loadData();
}

function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    title: row.title || '',
    variant: row.variant || '',
    platform_product_id: row.platform_product_id || '',
    platform_variant_id: row.platform_variant_id || '',
    platform_sku: row.platform_sku || '',
    sales_status: row.sales_status || '',
    owner: row.owner || '',
    leader: row.leader || '',
    source_old_sku_code: row.source_old_sku_code || row.internal_legacy_sku_code || '',
  });
  editVisible.value = true;
}

async function saveEdit() {
  const payload = {};
  for (const field of ['title', 'variant', 'platform_product_id', 'platform_variant_id', 'platform_sku', 'sales_status', 'owner', 'leader', 'source_old_sku_code']) {
    if (String(editForm[field] || '').trim()) payload[field] = String(editForm[field]).trim();
  }
  if (!Object.keys(payload).length) { message.value = '请至少填写一个需要修改的字段'; messageType.value = 'warning'; return; }
  editSaving.value = true;
  const response = await updatePlatformProductDetail(editForm.id, payload);
  editSaving.value = false;
  if (!response.success) { message.value = response.message || '保存失败'; messageType.value = 'error'; return; }
  editVisible.value = false;
  message.value = '平台商品明细已更新'; messageType.value = 'success';
  await loadData();
}

function bulkPayload(preview = false) {
  const fields = {};
  for (const field of ['title', 'variant', 'sales_status', 'owner', 'leader']) {
    if (String(bulkForm[field] || '').trim()) fields[field] = String(bulkForm[field]).trim();
  }
  const payload = {
    match_type: bulkForm.match_type,
    spu_code: bulkForm.spu_code.trim(),
    fields,
    preview,
  };
  // Omit ids when nothing is selected so the backend updates all exact-SPU
  // matches, including rows on other pages.  A selection explicitly limits
  // the operation to those records.
  if (selectedRows.value.length) payload.ids = selectedRows.value.map((row) => ({ id: row.id }));
  return payload;
}

function openBulk() { bulkPreview.value = null; bulkVisible.value = true; }

async function previewBulk() {
  if (!bulkForm.spu_code.trim()) { message.value = '请输入精确 SPU 编码'; messageType.value = 'warning'; return; }
  bulkSaving.value = true;
  const response = await bulkUpdatePlatformProductDetails(bulkPayload(true));
  bulkSaving.value = false;
  if (!response.success) { message.value = response.message || '匹配失败'; messageType.value = 'error'; return; }
  bulkPreview.value = Number(response.data?.matched || 0);
}

async function saveBulk() {
  if (!bulkForm.spu_code.trim()) { message.value = '请输入精确 SPU 编码'; messageType.value = 'warning'; return; }
  const payload = bulkPayload(false);
  if (!Object.keys(payload.fields).length) { message.value = '请至少填写一个需要修改的字段'; messageType.value = 'warning'; return; }
  const matched = bulkPreview.value === null ? '尚未预览' : `${bulkPreview.value} 条`;
  const scope = selectedRows.value.length
    ? `仅修改已选择的 ${selectedRows.value.length} 条记录`
    : '未选择记录，将修改该精确 SPU 的全部匹配记录（含其他分页）';
  try {
    await ElMessageBox.confirm(`预览匹配 ${matched}。${scope}。确认继续吗？`, '批量修改确认', { type: 'warning' });
  } catch { return; }
  bulkSaving.value = true;
  const response = await bulkUpdatePlatformProductDetails(payload);
  bulkSaving.value = false;
  if (!response.success) { message.value = response.message || '批量修改失败'; messageType.value = 'error'; return; }
  const result = response.data || {};
  bulkVisible.value = false;
  selectedRows.value = [];
  message.value = `批量修改完成：匹配 ${result.matched || 0} 条，更新 ${result.updated || 0} 条，无变化 ${result.unchanged || 0} 条${result.errors?.length ? `，失败 ${result.errors.length} 条` : ''}`;
  messageType.value = result.errors?.length ? 'warning' : 'success';
  await loadData();
}

function salesStatusType(value) {
  if (/active|on.?sale|在售/i.test(String(value || ''))) return 'success';
  if (/inactive|off.?sale|停售/i.test(String(value || ''))) return 'info';
  if (/draft|草稿/i.test(String(value || ''))) return 'warning';
  return 'info';
}

function optionRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (Array.isArray(data?.results) ? data.results : []);
}

async function loadReferenceOptions() {
  const [platformResponse, storeResponse] = await Promise.all([
    fetchPlatforms({ page: 1, page_size: 100, status: 'active' }),
    fetchStores({ page: 1, page_size: 100, status: 'active' }),
  ]);
  platformOptions.value = optionRows(platformResponse).map((item) => ({
    label: `${item.name || item.code} · ${item.code || item.id}`,
    value: item.id,
  }));
  storeOptions.value = optionRows(storeResponse).map((item) => ({
    label: `${item.name || item.code} · ${item.code || item.id}`,
    value: item.id,
  }));
}

async function loadCategories() {
  const response = await fetchProductCategories({ page: 1, page_size: 500, status: 'active' });
  const data = response?.data;
  categories.value = Array.isArray(data) ? data : (Array.isArray(data?.results) ? data.results : []);
}

async function onImport(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  importDialog.value = true;
  importMode.value = 'full';
  importing.value = true; importStep.value = 1; importStatus.value = '正在上传文件，服务器正在解析并校验数据，请勿关闭页面。'; importFileName.value = file.name; importElapsedSeconds.value = 0; importResult.value = null;
  const startedAt = Date.now(); clearInterval(importTimer); importTimer = setInterval(() => { importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); }, 1000);
  try {
    const response = await importPlatformProductDetails(file, { dryRun: false });
    importResult.value = response?.data || response;
    if (response?.success) {
      importStep.value = 3;
      importStatus.value = importHasWarnings.value ? '导入完成，但有部分数据未写入，请查看下方汇总。' : '导入完成，列表数据已刷新。';
      message.value = importHasWarnings.value ? '导入完成，但有部分数据被跳过，请查看导入结果。' : '导入完成';
      messageType.value = importHasWarnings.value ? 'warning' : 'success';
      filters.page = 1;
      await loadData();
    }
    else { importStatus.value = response?.message || '导入失败，请根据结果信息修正文件后重试。'; message.value = importStatus.value; messageType.value = 'error'; }
  } finally { importing.value = false; importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); clearInterval(importTimer); importTimer = null; }
}

function downloadVariantProductIdTemplate() {
  const headers = ['变体ID', '平台商品ID'];
  const example = ['V-1001', 'P-1001'];
  const csv = `\ufeff${headers.map(csvCell).join(',')}\r\n${example.map(csvCell).join(',')}\r\n`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '平台商品ID按变体ID导入模板.csv';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function onVariantProductIdImport(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  importDialog.value = true;
  importMode.value = 'variant_product_id';
  importing.value = true; importStep.value = 1; importStatus.value = '正在按变体ID匹配并更新平台商品ID，请勿关闭页面。'; importFileName.value = file.name; importElapsedSeconds.value = 0; importResult.value = null;
  const startedAt = Date.now(); clearInterval(importTimer); importTimer = setInterval(() => { importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); }, 1000);
  try {
    const response = await importPlatformProductIds(file, { dryRun: false });
    importResult.value = response?.data || response;
    if (response?.success) {
      importStep.value = 3;
      importStatus.value = importHasWarnings.value ? '变体ID导入完成，但有部分数据未更新，请查看下方汇总。' : '变体ID导入完成，列表数据已刷新。';
      message.value = importHasWarnings.value ? '变体ID导入完成，但有部分数据被跳过，请查看导入结果。' : `变体ID导入完成：更新 ${importSummary.value.updated} 条`;
      messageType.value = importHasWarnings.value ? 'warning' : 'success';
      filters.page = 1;
      await loadData();
    }
    else { importStatus.value = response?.message || '导入失败，请根据结果信息修正文件后重试。'; message.value = importStatus.value; messageType.value = 'error'; }
  } finally { importing.value = false; importElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000); clearInterval(importTimer); importTimer = null; }
}

onMounted(async () => {
  await Promise.all([loadReferenceOptions(), loadCategories()]);
  await loadData();
});
onUnmounted(() => clearInterval(importTimer));
</script>

<style scoped>
.page-message { margin-bottom: 16px; }
.template-button, .format-button, .import-button, .variant-id-import-button { min-width: 116px; height: 36px; padding: 0 14px; }
.import-button { min-width: 144px; }
.variant-id-import-button { min-width: 190px; }
.template-help { margin: 0 0 14px; color: #475569; line-height: 1.6; }
.template-fields :deep(.cell) { line-height: 1.45; }
.detail-workspace { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 16px; align-items: start; }
.category-panel, .detail-content { min-width: 0; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.category-panel { min-height: 640px; padding: 14px; }
.panel-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.category-panel :deep(.el-tree) { margin-top: 12px; }
.detail-content { padding: 0 12px 12px; }
.bulk-field { margin-top: 8px; }
.resource-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(112px, 160px)) minmax(180px, 1fr);
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}
.summary-item { min-height: 74px; padding: 14px 16px; border-right: 1px solid #e5eaf0; }
.summary-item:last-child { border-right: 0; }
.summary-item span { display: block; color: #64748b; font-size: 12px; }
.summary-item strong { display: block; margin-top: 8px; color: #172033; font-size: 20px; }
.summary-item--scope strong { font-size: 15px; }
.resource-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 170px 190px 160px auto;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid #dbe3ec;
  background: #fff;
}
.toolbar-actions { display: flex; gap: 8px; }
.resource-table { min-width: 0; margin-top: 16px; overflow: hidden; }
.resource-table :deep(.el-table) { width: 100%; }
.resource-pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 2px 68px;
  color: #64748b;
  font-size: 13px;
}
.resource-pagination :deep(.el-pagination) {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 100%;
  margin-left: auto;
}
.import-status { min-height: 130px; margin-top: 24px; padding: 16px; border-radius: 8px; background: #f8fafc; }
.import-status p { margin: 0 0 8px; }
.import-meta { color: #64748b; font-size: 13px; }
.import-result-panel { margin-top: 16px; padding: 12px; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.import-result-panel--warning { border-color: #f3c27a; background: #fffaf0; }
.import-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.import-summary-item { padding: 9px 10px; border: 1px solid #e5eaf0; border-radius: 6px; background: #fff; }
.import-summary-item span { display: block; color: #64748b; font-size: 12px; }
.import-summary-item strong { display: block; margin-top: 4px; color: #172033; font-size: 18px; }
.import-warning { color: #9a5b00; line-height: 1.6; }
.import-success { color: #2d8a45; }
.import-errors { margin-top: 12px; color: #b42318; line-height: 1.6; }
.import-errors ul { margin: 4px 0 8px; padding-left: 20px; }
@media (max-width: 560px) { .import-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) {
  .detail-workspace { grid-template-columns: 210px minmax(0, 1fr); }
  .resource-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n + 2) { border-bottom: 1px solid #e5eaf0; }
  .resource-toolbar { grid-template-columns: 1fr 1fr; }
  .resource-toolbar > .el-input { grid-column: 1 / -1; }
  .toolbar-actions { justify-content: flex-end; }
}
@media (max-width: 760px) {
  .detail-workspace { grid-template-columns: 1fr; }
  .category-panel { min-height: 0; }
  .resource-pagination { flex-direction: column; align-items: stretch; }
  .resource-pagination :deep(.el-pagination) { justify-content: flex-start; margin-left: 0; }
}
</style>
