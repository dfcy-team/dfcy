<template>
  <section class="archive-page">
    <header class="archive-header">
      <div>
        <h1>开发产品档案</h1>
        <p>虚拟库存测品独立于正式商品；完成确认后才允许人工转正。</p>
      </div>
      <el-button type="primary" @click="openCreate">新建测品档案</el-button>
    </header>

    <el-alert
      title="测品仅记录平台虚拟库存，不会发布到外部平台。转正动作只生成或关联内部商品档案。"
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
      <el-table-column label="虚拟库存" width="210">
        <template #default="{ row }">
          <span>{{ row.platform || 'internal' }} / {{ row.site || 'internal' }}</span>
          <small class="sku-line">{{ row.virtual_inventory_sku }} × {{ row.virtual_inventory_qty }}</small>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="260">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button v-if="row.status === 'trial'" link type="warning" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.status === 'trial'" link type="success" @click="confirmTrial(row)">确认测品</el-button>
          <el-button v-if="row.status === 'confirmed'" link type="danger" @click="formalize(row)">人工转正</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !archives.length" description="暂无开发产品档案" />

    <el-dialog v-model="formOpen" :title="editing ? '编辑虚拟测品档案' : '新建虚拟测品档案'" width="620px">
      <el-form :model="form" label-position="top">
        <el-form-item label="开发项目" required><el-input v-model="form.project" :disabled="editing" placeholder="填写开发项目 ID" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="商品名称"><el-input v-model="form.product_name" /></el-form-item>
          <el-form-item label="品类" required>
            <el-select v-model="form.category_node" filterable clearable placeholder="请选择 L3 分类" style="width: 100%">
              <el-option v-for="category in categoryOptions" :key="category.id" :label="category.path" :value="category.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="平台"><el-input v-model="form.platform" placeholder="shopee" /></el-form-item>
          <el-form-item label="站点"><el-input v-model="form.site" placeholder="TH" /></el-form-item>
          <el-form-item label="虚拟库存数量"><el-input-number v-model="form.virtual_inventory_qty" :min="0" /></el-form-item>
        </div>
        <el-form-item label="测品备注"><el-input v-model="form.test_notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="formOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存档案</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailOpen" title="开发产品档案详情" size="480px">
      <template v-if="selected">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="档案号">{{ selected.archive_no }}</el-descriptions-item>
          <el-descriptions-item label="开发项目">{{ selected.project_no }} (#{{ selected.project_id || selected.project }})</el-descriptions-item>
          <el-descriptions-item label="商品名称">{{ selected.product_name }}</el-descriptions-item>
          <el-descriptions-item label="品类">{{ categoryLabel(selected) }}</el-descriptions-item>
          <el-descriptions-item label="虚拟库存">{{ selected.virtual_inventory_sku }} × {{ selected.virtual_inventory_qty }}</el-descriptions-item>
          <el-descriptions-item label="当前状态"><el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item v-if="selected.formal_spu_code" label="正式 SPU">{{ selected.formal_spu_code }}</el-descriptions-item>
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
  updateDevelopmentProductArchive
} from '../../api/development';
import { fetchProductCategories } from '../../api/products';
import { collectionRows } from '../../utils/businessResponse';

const archives = ref([]);
const loading = ref(false);
const saving = ref(false);
const search = ref('');
const status = ref('');
const formOpen = ref(false);
const editing = ref(false);
const selected = ref(null);
const detailOpen = ref(false);
const categories = ref([]);
const form = reactive({ id: null, project: '', product_name: '', category_node: null, platform: 'internal', site: 'internal', virtual_inventory_qty: 0, test_notes: '' });

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
  return categories.value
    .filter((item) => item.is_active && Number(item.level) === 3)
    .map((item) => ({ ...item, path: pathFor(item) }));
});
const categoryLabel = (row) => row.category_path || row.category_name || row.category || '—';

const statusLabels = { trial: '虚拟测品', confirmed: '测品已确认', formalized: '已转正式档案', cancelled: '已取消' };
const statusLabel = (value) => statusLabels[value] || value || '未知';
const statusType = (value) => ({ trial: 'warning', confirmed: 'success', formalized: 'primary', cancelled: 'info' }[value] || 'info');
const formatDate = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '';
const rowsFrom = (response) => {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  return data?.results || data?.items || [];
};

async function load() {
  loading.value = true;
  const [response, categoryResponse] = await Promise.all([
    fetchDevelopmentProductArchives({ search: search.value, status: status.value }),
    fetchProductCategories()
  ]);
  loading.value = false;
  if (response?.success) archives.value = rowsFrom(response);
  else ElMessage.error(response?.message || '档案加载失败');
  if (categoryResponse?.success) categories.value = collectionRows(categoryResponse.data);
}

function resetForm() { Object.assign(form, { id: null, project: '', product_name: '', category_node: null, platform: 'internal', site: 'internal', virtual_inventory_qty: 0, test_notes: '' }); }
function openCreate() { editing.value = false; resetForm(); formOpen.value = true; }
function openEdit(row) { editing.value = true; Object.assign(form, { ...row, category_node: row.category_node || null, project: row.project_id || row.project }); formOpen.value = true; }

async function save() {
  if (!form.project) return ElMessage.warning('请填写开发项目 ID');
  if (!form.category_node) return ElMessage.warning('请选择有效的末级商品分类');
  saving.value = true;
  const payload = { project: Number(form.project), product_name: form.product_name, category_node: form.category_node, platform: form.platform, site: form.site, virtual_inventory_qty: form.virtual_inventory_qty, test_notes: form.test_notes };
  const response = editing.value ? await updateDevelopmentProductArchive(form.id, payload) : await createDevelopmentProductArchive(payload);
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '档案保存失败');
  formOpen.value = false;
  ElMessage.success('档案已保存');
  await load();
}

async function openDetail(row) {
  const response = await fetchDevelopmentProductArchive(row.id);
  if (response?.success) { selected.value = response.data; detailOpen.value = true; }
  else ElMessage.error(response?.message || '档案详情加载失败');
}

async function confirmTrial(row) {
  try { await ElMessageBox.confirm('确认测品已完成且通过？确认后才可执行人工转正。', '确认测品完成', { type: 'warning' }); } catch { return; }
  const response = await confirmDevelopmentProductArchive(row.id, { test_result: 'pass' });
  if (!response?.success) return ElMessage.error(response?.message || '测品确认失败');
  ElMessage.success('测品已确认');
  await load();
}

async function formalize(row) {
  try { await ElMessageBox.confirm('该动作只生成或关联内部正式商品档案，不会发布外部平台。继续？', '人工转正', { type: 'success' }); } catch { return; }
  const response = await formalizeDevelopmentProductArchive(row.id);
  if (!response?.success) return ElMessage.error(response?.message || '档案转正失败');
  ElMessage.success(`已转正为内部商品档案 ${response.data?.spu_code || ''}`);
  await load();
}

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
.audit-title { margin: 24px 0 14px; font-weight: 600; color: #25324b; }
@media (max-width: 760px) { .archive-header { flex-direction: column; gap: 14px; } .archive-filters { flex-wrap: wrap; } .archive-filters .el-input { width: 100%; } }
</style>
