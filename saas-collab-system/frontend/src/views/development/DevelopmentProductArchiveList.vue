<template>
  <section class="archive-page">
    <header class="archive-header">
      <div>
        <h1>开发产品档案</h1>
        <p>开发测品独立于正式商品；实际小单达标可直接转正，虚拟库存测品通过后先进入上新计划再转正。</p>
      </div>
      <el-button type="primary" @click="openCreate">新建测品档案</el-button>
    </header>

    <el-alert
      title="开发编码仅用于测品，不会发布到外部平台；小单测款达标可直接转正，虚拟库存测款通过后先进入上新计划。"
      type="info"
      :closable="false"
      show-icon
      class="archive-boundary"
    />

    <div class="archive-filters">
      <el-input v-model="search" clearable placeholder="搜索档案号、项目号或商品名称" @keyup.enter="load" />
      <el-select v-model="status" clearable placeholder="全部状态" @change="load">
        <el-option label="虚拟测品" value="trial" />
        <el-option label="测品已确认" value="confirmed" />
        <el-option label="已转正式档案" value="formalized" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="archives" v-loading="loading" row-key="id" class="archive-table">
      <el-table-column prop="archive_no" label="档案号" width="180" />
      <el-table-column prop="project_no" label="开发项目" width="180" />
      <el-table-column prop="product_name" label="商品名称" min-width="180" />
      <el-table-column label="品类" min-width="240"><template #default="{ row }"><span>{{ categoryLabel(row) }}</span></template></el-table-column>
      <el-table-column label="测款模式" width="150"><template #default="{ row }"><el-tag effect="plain" :type="trialModeType(row.trial_mode || row.mode)">{{ trialModeLabel(row.trial_mode || row.mode) }}</el-tag></template></el-table-column>
      <el-table-column label="平台 / 站点 / 店铺" min-width="240">
        <template #default="{ row }">
          <span>{{ row.platform || 'internal' }} / {{ row.site || 'internal' }}</span>
          <small v-if="row.store_name || row.store_code" class="sku-line">{{ row.store_name || row.store_code }}</small>
          <small class="sku-line">{{ row.virtual_inventory_sku }} × {{ row.virtual_inventory_qty }}</small>
        </template>
      </el-table-column>
      <el-table-column label="开发测品 SPU / SKU" min-width="190">
        <template #default="{ row }">
          <span>{{ row.trial_spu_code || '未生成' }}</span>
          <small v-if="row.trial_sku_code" class="sku-line">{{ row.trial_sku_code }}</small>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="330">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button v-if="row.status === 'trial'" link type="warning" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="!row.trial_spu_code && row.status !== 'formalized'" link type="success" @click="openTrialGenerator(row)">生成测品 SPU/SKU</el-button>
          <el-button v-if="row.status === 'trial'" link type="success" @click="confirmTrial(row)">确认测品</el-button>
          <el-button v-if="row.status === 'confirmed' && isVirtualTrial(row)" link type="warning" @click="createLaunchPlan(row)">进入上新计划</el-button>
          <el-button v-if="row.status === 'confirmed' && !isVirtualTrial(row)" link type="danger" @click="formalize(row)">人工转正</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !archives.length" description="暂无开发产品档案" />

    <el-dialog v-model="formOpen" :title="editing ? '编辑虚拟测品档案' : '新建虚拟测品档案'" width="660px">
      <el-form :model="form" label-position="top">
        <el-form-item label="开发项目" required>
          <el-select v-model="form.project" filterable clearable :disabled="editing" placeholder="选择开发项目" style="width: 100%" @change="onProjectChange">
            <el-option v-for="project in projectOptions" :key="project.id" :label="`${project.project_no} · ${project.product_name}`" :value="Number(project.id)" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="商品名称"><el-input v-model="form.product_name" /></el-form-item>
          <el-form-item label="品类" required>
              <el-select v-model="form.category_node" filterable clearable placeholder="请选择 L2 或 L3 分类" style="width: 100%">
              <el-option v-for="category in categoryOptions" :key="category.id" :label="category.path" :value="category.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="平台">
            <el-select v-model="form.platform_master" filterable clearable placeholder="选择启用平台" style="width: 100%" @change="onPlatformChange">
              <el-option v-for="item in platformOptions" :key="item.id" :label="`${item.name || item.code} (${item.code})`" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="国家站点">
            <el-select v-model="form.site" filterable clearable placeholder="选择国家站点" style="width: 100%" @change="onSiteChange">
              <el-option v-for="item in siteOptions" :key="item.id || item.country_code" :label="`${item.name || item.country_code} (${item.country_code || item.code})`" :value="String(item.country_code || item.code || '').toUpperCase()" />
            </el-select>
          </el-form-item>
          <el-form-item label="店铺">
            <el-select v-model="form.store_master" filterable clearable placeholder="选择启用店铺" style="width: 100%" @change="onStoreChange">
              <el-option v-for="item in storeOptions" :key="item.id" :label="`${item.name || item.code} (${item.country_code})`" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="虚拟库存数量"><el-input-number v-model="form.virtual_inventory_qty" :min="0" /></el-form-item>
          <el-form-item label="测款模式" required>
            <el-select v-model="form.trial_mode" disabled style="width: 100%">
              <el-option label="实际小单测款" value="small_order" />
              <el-option label="虚拟库存测款" value="virtual" />
            </el-select>
            <small class="field-help">测款模式继承开发项目。虚拟库存测款通过后先进入上新计划；实际小单测款达标可直接转正。</small>
          </el-form-item>
        </div>
        <el-form-item label="测品备注"><el-input v-model="form.test_notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="formOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存档案</el-button></template>
    </el-dialog>

    <el-dialog v-model="trialOpen" title="生成测品 SPU/SKU" width="520px">
      <el-form :model="trialForm" label-position="top">
        <el-form-item label="开发 SPU 编码" required><el-input v-model="trialForm.development_spu_code" placeholder="仅 A-Z/0-9，至少含一个字母" /></el-form-item>
        <el-form-item label="颜色" required>
          <el-select v-model="trialForm.color_code" filterable placeholder="请选择启用颜色" style="width: 100%">
            <el-option v-for="item in activeColors" :key="item.code" :label="`${item.name || item.code} · ${item.code}`" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-alert title="开发 SKU 三段 = 人工开发 SPU - 颜色 - 规格；无规格时规格段固定为 STD。" type="info" :closable="false" />
        <el-form-item label="正式属性编码（转正式使用）"><el-input v-model="trialForm.season_code" maxlength="1" placeholder="0-9" /></el-form-item>
        <el-form-item v-for="dimension in trialDimensions" :key="dimension.code" :label="dimension.name || dimension.code" required>
          <el-select v-if="dimension.values?.length" v-model="trialForm.spec_values[dimension.code]" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="value in dimension.values" :key="value" :label="value" :value="value" />
          </el-select>
          <el-input v-else v-model="trialForm.spec_values[dimension.code]" />
        </el-form-item>
        <el-form-item label="开发 SKU 预览"><el-input :model-value="developmentSkuPreview" readonly /></el-form-item>
      </el-form>
      <template #footer><el-button @click="trialOpen = false">取消</el-button><el-button type="primary" :loading="trialSaving" @click="generateTrial">生成测品</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailOpen" title="开发产品档案详情" size="500px">
      <template v-if="selected">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="档案号">{{ selected.archive_no }}</el-descriptions-item>
          <el-descriptions-item label="开发项目">{{ selected.project_no }} (#{{ selected.project_id || selected.project }})</el-descriptions-item>
          <el-descriptions-item label="商品名称">{{ selected.product_name }}</el-descriptions-item>
          <el-descriptions-item label="品类">{{ categoryLabel(selected) }}</el-descriptions-item>
          <el-descriptions-item label="测款模式"><el-tag effect="plain" :type="trialModeType(selected.trial_mode || selected.mode)">{{ trialModeLabel(selected.trial_mode || selected.mode) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="平台 / 站点 / 店铺">{{ selected.platform || 'internal' }} / {{ selected.site || 'internal' }} / {{ selected.store_name || selected.store_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="虚拟库存">{{ selected.virtual_inventory_sku }} × {{ selected.virtual_inventory_qty }}</el-descriptions-item>
          <el-descriptions-item label="开发测品 SPU / SKU">{{ selected.trial_spu_code || '未生成' }} / {{ selected.trial_sku_code || '未生成' }}</el-descriptions-item>
          <el-descriptions-item v-if="selected.formal_spu_code" label="正式 SPU / SKU">{{ selected.formal_spu_code }} / {{ selected.formal_sku_code || '未生成' }}</el-descriptions-item>
          <el-descriptions-item label="当前状态"><el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="测品备注">{{ selected.test_notes || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="audit-title">审计记录</div>
        <el-timeline>
          <el-timeline-item v-for="event in selected.events || []" :key="event.id || `${event.action}-${event.created_at}`" :timestamp="formatDate(event.created_at)">{{ event.action }} → {{ event.to_status }}</el-timeline-item>
        </el-timeline>
      </template>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  confirmDevelopmentProductArchive,
  createDevelopmentProductArchive,
  fetchDevelopmentProductArchive,
  fetchDevelopmentProductArchives,
  formalizeDevelopmentProductArchive,
  generateDevelopmentProductArchiveTrial,
  createDevelopmentLaunchPlan,
  fetchDevelopmentProjects,
  updateDevelopmentProductArchive
} from '../../api/development';
import { fetchProductCategories, fetchProductColors } from '../../api/products';
import { fetchCountrySites, fetchPlatforms, fetchStores } from '../../api/masterData';
import { collectionRows } from '../../utils/businessResponse';

const archives = ref([]);
const loading = ref(false);
const saving = ref(false);
const trialSaving = ref(false);
const search = ref('');
const status = ref('');
const formOpen = ref(false);
const trialOpen = ref(false);
const editing = ref(false);
const selected = ref(null);
const trialArchive = ref(null);
const detailOpen = ref(false);
const categories = ref([]);
const projects = ref([]);
const platforms = ref([]);
const stores = ref([]);
const countrySites = ref([]);
const colors = ref([]);
const form = reactive({ id: null, project: null, product_name: '', category_node: null, platform_master: null, store_master: null, platform: 'internal', site: 'internal', virtual_inventory_qty: 0, trial_mode: 'small_order', test_notes: '' });
const trialForm = reactive({ development_spu_code: '', color_code: '', season_code: '0', spec_values: {} });

const categoryOptions = computed(() => {
  const byId = new Map(categories.value.map((item) => [Number(item.id), item]));
  const pathFor = (item) => {
    const parts = [];
    const seen = new Set();
    let current = item;
    while (current && !seen.has(Number(current.id))) {
      seen.add(Number(current.id));
      parts.unshift(`L${current.level} ${current.code} ${current.name}`);
      current = byId.get(Number(current.parent));
    }
    return parts.join(' / ');
  };
  return categories.value.filter((item) => item.is_active !== false && [2, 3].includes(Number(item.level))).map((item) => ({ ...item, path: pathFor(item) }));
});
const activePlatforms = computed(() => platforms.value.filter((item) => item.status === 'active'));
const projectOptions = computed(() => projects.value.filter((item) => item?.id && item.status !== 'cancelled'));
const selectedPlatform = computed(() => activePlatforms.value.find((item) => Number(item.id) === Number(form.platform_master)));
const platformOptions = computed(() => activePlatforms.value);
const siteOptions = computed(() => {
  const platformId = Number(form.platform_master);
  return countrySites.value.filter((item) => !item.platform_id || Number(item.platform_id) === platformId);
});
const storeOptions = computed(() => stores.value.filter((item) => item.status === 'active' && (!form.platform_master || Number(item.platform_id) === Number(form.platform_master)) && (!form.site || String(item.country_code || '').toUpperCase() === String(form.site || '').toUpperCase())));
const activeColors = computed(() => colors.value.filter((item) => item.is_active !== false));
const trialDimensions = computed(() => {
  const categoryId = Number(trialArchive.value?.category_node);
  return categoryOptions.value.find((item) => Number(item.id) === categoryId)?.spec_dimensions || [];
});
const developmentSkuPreview = computed(() => {
  const spu = String(trialForm.development_spu_code || '').trim().toUpperCase() || 'DEVSPU';
  const color = String(trialForm.color_code || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, 'X').replace(/^X+|X+$/g, '') || 'COLOR';
  const values = trialDimensions.value.map((dimension) => String(trialForm.spec_values[dimension.code] || '').trim().toUpperCase()).filter(Boolean);
  const spec = values.length ? values.join('X').replace(/[^A-Z0-9]+/g, 'X').replace(/^X+|X+$/g, '') : 'STD';
  return `${spu}-${color}-${spec}`;
});
const categoryLabel = (row) => row.category_path || row.category_name || row.category || '—';
const trialModeLabels = { small_order: '实际小单测款', virtual_inventory: '虚拟库存测款', virtual: '虚拟库存测款', small: '实际小单测款' };
const trialModeLabel = (value) => trialModeLabels[value] || value || '未设置';
const trialModeType = (value) => String(value || '').includes('virtual') || value === 'virtual' ? 'warning' : 'success';
const isVirtualTrial = (row) => ['virtual_inventory', 'virtual'].includes(row?.trial_mode || row?.mode);
const statusLabels = { trial: '虚拟测品', confirmed: '测品已确认', formalized: '已转正式档案', cancelled: '已取消' };
const statusLabel = (value) => statusLabels[value] || value || '未知';
const statusType = (value) => ({ trial: 'warning', confirmed: 'success', formalized: 'primary', cancelled: 'info' }[value] || 'info');
const formatDate = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '';
const rowsFrom = (response) => Array.isArray(response?.data) ? response.data : (response?.data?.results || response?.data?.items || []);
const normalizeId = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
};
const normalizeText = (value, fallback) => {
  const text = String(value ?? '').trim();
  return text || fallback;
};
const archiveFieldLabels = {
  project: '开发项目',
  product_name: '商品名称',
  category_node: 'L2/L3品类',
  platform_master: '平台',
  platform_id: '平台',
  store_master: '店铺',
  store_id: '店铺',
  platform: '平台',
  site: '国家站点',
  virtual_inventory_qty: '虚拟库存数量',
  test_notes: '备注'
};
const errorMessages = (value) => {
  if (Array.isArray(value)) return value.flatMap(errorMessages);
  if (value && typeof value === 'object') return Object.values(value).flatMap(errorMessages);
  return value === null || value === undefined || value === '' ? [] : [String(value)];
};
const localizeArchiveError = (value) => {
  const text = String(value || '');
  if (/this field may not be null/i.test(text)) return '不能为空';
  if (/this field is required/i.test(text)) return '为必填项';
  if (/a valid integer is required/i.test(text)) return '必须是有效的数字 ID';
  return text;
};
function formatArchiveError(response, fallback) {
  const details = response?.data && typeof response.data === 'object' && !Array.isArray(response.data) ? response.data : {};
  const fields = Object.entries(details).flatMap(([field, value]) => errorMessages(value).map((message) => `${archiveFieldLabels[field] || field}：${localizeArchiveError(message)}`));
  return fields.length ? `${fallback}：${fields.join('；')}` : response?.message || fallback;
}

async function fetchAllOptions(fetcher, params = {}) {
  const rows = [];
  for (let page = 1; page <= 100; page += 1) {
    const response = await fetcher({ ...params, page, page_size: 100 });
    if (!response?.success) return response;
    const batch = rowsFrom(response);
    rows.push(...batch);
    const count = Number(response?.data?.count);
    const hasMore = Boolean(response?.data?.next) || (Number.isFinite(count) && rows.length < count);
    if (!hasMore || batch.length === 0) break;
  }
  return { success: true, data: rows };
}

async function load() {
  loading.value = true;
  const [response, projectResponse, categoryResponse, colorResponse, platformResponse, storeResponse, siteResponse] = await Promise.all([
    fetchDevelopmentProductArchives({ search: search.value, status: status.value }),
    fetchAllOptions(fetchDevelopmentProjects),
    fetchAllOptions(fetchProductCategories),
    fetchAllOptions(fetchProductColors),
    fetchAllOptions(fetchPlatforms, { status: 'active' }),
    fetchAllOptions(fetchStores, { status: 'active' }),
    fetchAllOptions(fetchCountrySites, { status: 'active' })
  ]);
  loading.value = false;
  if (response?.success) archives.value = rowsFrom(response); else ElMessage.error(formatArchiveError(response, '档案加载失败'));
  if (projectResponse?.success) projects.value = rowsFrom(projectResponse);
  if (categoryResponse?.success) categories.value = collectionRows(categoryResponse.data);
  if (colorResponse?.success) colors.value = collectionRows(colorResponse.data);
  if (platformResponse?.success) platforms.value = rowsFrom(platformResponse);
  if (storeResponse?.success) stores.value = rowsFrom(storeResponse);
  if (siteResponse?.success) countrySites.value = rowsFrom(siteResponse);
}

function resetForm() { Object.assign(form, { id: null, project: null, product_name: '', category_node: null, platform_master: null, store_master: null, platform: 'internal', site: 'internal', virtual_inventory_qty: 0, trial_mode: 'small_order', test_notes: '' }); }
function openCreate() { editing.value = false; resetForm(); formOpen.value = true; }
function openEdit(row) { editing.value = true; Object.assign(form, { ...row, category_node: normalizeId(row.category_node), platform_master: normalizeId(row.platform_master ?? row.platform_id), store_master: normalizeId(row.store_master ?? row.store_id), project: normalizeId(row.project_id ?? row.project) }); formOpen.value = true; }
function onProjectChange(value) { const project = projects.value.find((item) => Number(item.id) === Number(value)); if (project) { form.product_name = project.product_name || ''; form.category_node = normalizeId(project.category_node); form.trial_mode = project.trial_mode || 'small_order'; } }
function onPlatformChange(value) { form.platform_master = normalizeId(value); const platform = activePlatforms.value.find((item) => Number(item.id) === Number(form.platform_master)); form.platform = platform?.code || 'internal'; form.site = 'internal'; form.store_master = null; }
function onSiteChange(value) { form.site = String(value || 'internal').toUpperCase(); if (!storeOptions.value.some((item) => Number(item.id) === Number(form.store_master))) form.store_master = null; }
function onStoreChange(value) { form.store_master = normalizeId(value); const store = stores.value.find((item) => Number(item.id) === Number(form.store_master)); if (store) { form.site = String(store.country_code || '').toUpperCase(); form.platform_master = normalizeId(store.platform_id); form.platform = selectedPlatform.value?.code || form.platform; } }

async function save() {
  const projectId = normalizeId(form.project);
  const categoryId = normalizeId(form.category_node);
  if (!projectId) return ElMessage.warning('请选择有效的开发项目');
  if (!categoryId) return ElMessage.warning('请选择有效的 L2 或 L3 商品分类');
  saving.value = true;
  const payload = {
    project: projectId,
    product_name: normalizeText(form.product_name, ''),
    category_node: categoryId,
    platform: normalizeText(form.platform, 'internal'),
    site: normalizeText(form.site, 'internal').toUpperCase(),
    virtual_inventory_qty: Math.max(Number(form.virtual_inventory_qty) || 0, 0),
    test_notes: normalizeText(form.test_notes, '')
  };
  const platformId = normalizeId(form.platform_master);
  const storeId = normalizeId(form.store_master);
  if (platformId !== null) payload.platform_master = platformId;
  if (storeId !== null) payload.store_master = storeId;
  const response = editing.value ? await updateDevelopmentProductArchive(form.id, payload) : await createDevelopmentProductArchive(payload);
  saving.value = false;
  if (!response?.success) return ElMessage.error(formatArchiveError(response, '档案保存失败'));
  formOpen.value = false; ElMessage.success('档案已保存'); await load();
}

function openTrialGenerator(row) {
  trialArchive.value = row;
  const specValues = {};
  const category = categoryOptions.value.find((item) => Number(item.id) === Number(row.category_node));
  for (const dimension of category?.spec_dimensions || []) specValues[dimension.code] = '';
  Object.assign(trialForm, { development_spu_code: row.development_spu_code || '', color_code: row.trial_color_code || activeColors.value[0]?.code || '', season_code: '0', spec_values: specValues });
  trialOpen.value = true;
}
async function generateTrial() {
  if (!trialArchive.value || !trialForm.development_spu_code.trim()) return ElMessage.warning('请输入开发 SPU 编码');
  if (!trialForm.color_code.trim()) return ElMessage.warning('请选择颜色');
  if (trialDimensions.value.some((dimension) => !trialForm.spec_values[dimension.code])) return ElMessage.warning('请完整填写规格');
  trialSaving.value = true;
  const response = await generateDevelopmentProductArchiveTrial(trialArchive.value.id, { development_spu_code: trialForm.development_spu_code.trim(), color_code: trialForm.color_code.trim(), season_code: trialForm.season_code || '0', spec_values: { ...trialForm.spec_values } });
  trialSaving.value = false;
  if (!response?.success) return ElMessage.error(formatArchiveError(response, '测品生成失败'));
  trialOpen.value = false; ElMessage.success(`测品已生成 ${response.data?.trial_spu_code || ''}`); await load();
}

async function openDetail(row) { const response = await fetchDevelopmentProductArchive(row.id); if (response?.success) { selected.value = response.data; detailOpen.value = true; } else ElMessage.error(formatArchiveError(response, '档案详情加载失败')); }
async function confirmTrial(row) { const message = isVirtualTrial(row) ? '确认测品已完成且通过？确认后将进入上新计划，实际准备上新时再转正。' : '确认测品已完成且通过？确认后才可执行人工转正。'; try { await ElMessageBox.confirm(message, '确认测品完成', { type: 'warning' }); } catch { return; } const response = await confirmDevelopmentProductArchive(row.id, { test_result: 'pass' }); if (!response?.success) return ElMessage.error(formatArchiveError(response, '测品确认失败')); await load(); }
async function createLaunchPlan(row) { try { await ElMessageBox.confirm('虚拟库存测款通过后先进入上新计划，实际准备上新时再转正。继续？', '进入上新计划', { type: 'warning' }); } catch { return; } const response = await createDevelopmentLaunchPlan({ project: row.project_id || row.project, archive: row.id, planned_launch_date: row.planned_launch_date || null, target_platforms: row.platform ? [row.platform] : [] }); if (!response?.success) return ElMessage.error(formatArchiveError(response, '上新计划创建失败')); ElMessage.success('已进入上新计划'); await load(); }
async function formalize(row) { try { await ElMessageBox.confirm('转正式后按正式规则生成另一套正式 SPU/SKU，并保留开发测品映射，不会发布外部平台。继续？', '人工转正', { type: 'success' }); } catch { return; } const response = await formalizeDevelopmentProductArchive(row.id); if (!response?.success) return ElMessage.error(formatArchiveError(response, '档案转正失败')); ElMessage.success(`已生成正式商品 ${response.data?.spu_code || ''}`); await load(); }

onMounted(load);
</script>

<style scoped>
.archive-page { padding: 24px; background: #f6f8fb; min-height: 100%; }
.archive-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.archive-header h1 { margin: 0 0 8px; color: #172033; }
.archive-header p { margin: 0; color: #718096; }
.archive-boundary { margin-bottom: 18px; }
.archive-filters { display: flex; gap: 12px; margin-bottom: 16px; }
.archive-filters .el-input { width: 300px; }
.archive-filters .el-select { width: 150px; }
.archive-table { background: #fff; }
.sku-line { display: block; color: #8a94a6; margin-top: 3px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.field-help { display: block; margin-top: 4px; color: #64748b; line-height: 1.4; }
.audit-title { margin: 24px 0 14px; font-weight: 600; color: #25324b; }
@media (max-width: 760px) { .archive-header { flex-direction: column; gap: 14px; } .archive-filters { flex-wrap: wrap; } .archive-filters .el-input { width: 100%; } }
</style>
