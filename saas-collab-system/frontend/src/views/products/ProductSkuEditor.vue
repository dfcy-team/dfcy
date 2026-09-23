<template>
  <section class="sku-editor" v-loading="loading">
    <header class="editor-head">
      <div class="head-main">
        <el-button text @click="goBack">← 返回商品明细</el-button>
        <div>
          <div class="eyebrow">单个 SKU 编辑</div>
          <h1>{{ form.sku_code || '商品明细' }}</h1>
        </div>
        <el-tag :type="form.is_active ? 'success' : 'info'">{{ form.is_active ? '在售' : '停用' }}</el-tag>
      </div>
      <div class="head-actions">
        <el-button @click="reload">取消修改</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </header>

    <div class="editor-layout">
      <aside class="anchor-nav">
        <strong>编辑目录</strong>
        <a v-for="item in anchors" :key="item.id" :href="`#${item.id}`">{{ item.label }}</a>
      </aside>

      <main class="editor-main">
        <el-alert title="SKU 编码、所属 SPU、颜色和规格生成后不可修改；库存来自仓库同步，仅供查看。" type="info" :closable="false" show-icon />

        <section id="basic" class="editor-card">
          <div class="section-title"><h2>基本信息</h2><span>维护 SKU 名称、图片和销售状态</span></div>
          <div class="basic-grid">
            <div class="image-box" @click="previewVisible = Boolean(form.image_url)">
              <el-image v-if="form.image_url" :src="imageSrc(form.image_url)" fit="contain" />
              <span v-else>暂无图片</span>
              <small>{{ form.image_url ? '点击放大' : '填写图片链接后预览' }}</small>
            </div>
            <el-form label-position="top" class="form-grid">
              <el-form-item label="SKU 商品名称" class="span-2"><el-input v-model="form.product_name" maxlength="200" show-word-limit /></el-form-item>
              <el-form-item label="新 SKU 编码"><el-input v-model="form.sku_code" disabled /></el-form-item>
              <el-form-item label="旧 SKU 编码">
                <el-input
                  v-model="form.legacy_sku_code"
                  maxlength="160"
                  :disabled="!canEditLegacyCodes"
                  :placeholder="canEditLegacyCodes ? '请输入旧 SKU 编码' : '仅管理员可编辑'"
                  data-testid="legacy-sku-code-input"
                />
                <div v-if="!canEditLegacyCodes" class="field-hint">仅平台超级管理员或租户管理员可修改</div>
              </el-form-item>
              <el-form-item label="所属 SPU"><el-input :model-value="String(form.spu || '')" disabled /></el-form-item>
              <el-form-item label="颜色 / 规格"><el-input :model-value="variantText" disabled /></el-form-item>
              <el-form-item label="计量单位"><el-input v-model="form.unit" placeholder="如：件" /></el-form-item>
              <el-form-item label="销售状态"><el-switch v-model="form.is_active" active-text="在售" inactive-text="停用" /></el-form-item>
              <el-form-item label="图片链接" class="span-2"><el-input v-model="form.image_url" placeholder="https://... 或 /media/product-images/..." /></el-form-item>
            </el-form>
          </div>
        </section>

        <section id="price" class="editor-card">
          <div class="section-title"><h2>价格信息</h2><span>维护参考成本价</span></div>
          <el-form label-position="top" class="compact-grid">
            <el-form-item label="参考成本价"><el-input-number v-model="form.purchase_price" :min="0" :precision="4" controls-position="right" /></el-form-item>
          </el-form>
        </section>

        <section id="attributes" class="editor-card">
          <div class="section-title"><h2>商品属性</h2><span>补充商品说明与报关信息</span></div>
          <el-form label-position="top" class="form-grid">
            <el-form-item label="产地国家"><el-input v-model="form.origin_country" /></el-form-item>
            <el-form-item label="HS 编码"><el-input v-model="form.hs_code" /></el-form-item>
            <el-form-item label="材质"><el-input v-model="form.material" /></el-form-item>
            <el-form-item label="卖点" class="span-2"><el-input v-model="form.selling_points" type="textarea" :rows="2" /></el-form-item>
            <el-form-item label="商品描述" class="span-2"><el-input v-model="form.product_description" type="textarea" :rows="4" /></el-form-item>
          </el-form>
        </section>

        <section id="other" class="editor-card">
          <div class="section-title"><h2>其他信息</h2><span>普通 SKU 的附加设置</span></div>
          <el-form label-position="top" class="compact-grid">
            <el-form-item label="库存类型">
              <el-select v-model="form.inventory_type" clearable placeholder="请选择">
                <el-option label="实体商品" value="physical" />
                <el-option label="虚拟商品" value="virtual" />
              </el-select>
            </el-form-item>
          </el-form>
        </section>

        <section id="package" class="editor-card">
          <div class="section-title"><h2>重量信息</h2><span>尺寸统一使用厘米，重量使用克</span></div>
          <el-form label-position="top" class="measure-grid">
            <el-form-item label="包装重量 (g)"><el-input-number v-model="form.package_weight" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="长 (cm)"><el-input-number v-model="form.package_length_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="宽 (cm)"><el-input-number v-model="form.package_width_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="高 (cm)"><el-input-number v-model="form.package_height_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="包装体积 (m³)"><el-input-number v-model="form.package_volume" :min="0" :precision="6" /></el-form-item>
            <el-button class="volume-button" @click="calculateVolume">按长宽高计算体积</el-button>
          </el-form>
        </section>

        <section id="mapping" class="editor-card">
          <div class="section-title"><h2>店铺 SKU 匹配</h2><span>展示各店铺与当前内部 SKU 的对应关系</span></div>
          <el-table :data="platformRows" empty-text="暂无平台 SKU 映射">
            <el-table-column prop="platform_name" label="平台" width="120" />
            <el-table-column prop="store_name" label="店铺" min-width="150" />
            <el-table-column prop="title" label="平台商品" min-width="210" show-overflow-tooltip />
            <el-table-column prop="platform_product_id" label="Item ID" min-width="140" />
            <el-table-column prop="variant" label="属性" min-width="140" show-overflow-tooltip />
            <el-table-column prop="platform_sku" label="平台 SKU" min-width="150" />
            <el-table-column label="映射状态" width="110"><template #default="{ row }"><el-tag size="small" :type="row.mapping ? 'success' : 'info'">{{ row.mapping ? '已映射' : '待确认' }}</el-tag></template></el-table-column>
          </el-table>
        </section>

        <section id="inventory" class="editor-card">
          <div class="section-title"><h2>仓库与库存</h2><span>仓库同步库存，只读展示</span></div>
          <el-table :data="warehouseRows" empty-text="暂无仓库库存记录">
            <el-table-column prop="warehouse_name" label="仓库" min-width="160" />
            <el-table-column prop="warehouse_code" label="仓库编码" width="130" />
            <el-table-column prop="source_sku" label="仓库 SKU" min-width="150" />
            <el-table-column prop="on_hand_qty" label="在库数量" width="110" align="right" />
            <el-table-column prop="reserved_qty" label="已锁" width="90" align="right" />
            <el-table-column prop="available_qty" label="可用库存" width="110" align="right" />
            <el-table-column prop="snapshot_at_utc" label="库存更新时间" min-width="180" />
          </el-table>
        </section>

        <section id="history" class="editor-card">
          <div class="section-title"><h2>修改记录</h2><span>追踪当前 SKU 的操作历史</span></div>
          <el-table :data="auditRows" empty-text="暂无修改记录">
            <el-table-column prop="created_at" label="时间" min-width="180" />
            <el-table-column prop="operator_name" label="操作人" width="130" />
            <el-table-column prop="action" label="操作" width="140" />
            <el-table-column prop="module" label="模块" min-width="140" />
          </el-table>
        </section>
      </main>
    </div>

    <el-image-viewer v-if="previewVisible" :url-list="[imageSrc(form.image_url)]" @close="previewVisible = false" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { fetchProductSku, updateProductSku, updateProductSkuStatus } from '../../api/products';
import { fetchPlatformProductDetails, fetchWarehouseSkus } from '../../api/platformProductDetails';
import { fetchOperationLogs } from '../../api/audit';
import { apiBaseUrl } from '../../api/baseUrl';
import { collectionRows, detailData } from '../../utils/businessResponse';
import { useAuthStore } from '../../stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const previewVisible = ref(false);
const platformRows = ref([]);
const warehouseRows = ref([]);
const auditRows = ref([]);
const originalActive = ref(true);
const canEditLegacyCodes = computed(() => Boolean(
  auth.currentUser?.is_superuser || auth.currentUser?.roles?.includes('administrator')
));
const form = reactive({});
const anchors = [
  { id: 'basic', label: '基本信息' }, { id: 'price', label: '价格信息' },
  { id: 'attributes', label: '商品属性' }, { id: 'other', label: '其他信息' }, { id: 'package', label: '重量信息' },
  { id: 'mapping', label: '店铺 SKU 匹配' }, { id: 'inventory', label: '仓库与库存' },
  { id: 'history', label: '修改记录' },
];
const variantText = computed(() => [form.color_code, form.specification].filter(Boolean).join(' / ') || '-');
const rowsOf = (response) => collectionRows(response?.data);
const imageSrc = (url) => !url || /^https?:/i.test(url) ? url : `${apiBaseUrl}${url}`;
const goBack = () => router.push('/products/details');

async function reload() {
  loading.value = true;
  const skuResponse = await fetchProductSku(route.params.id);
  if (!skuResponse.success) {
    ElMessage.error(skuResponse.message || '商品明细加载失败'); loading.value = false; return;
  }
  const sku = detailData(skuResponse.data) || skuResponse.data || {};
  Object.assign(form, sku);
  originalActive.value = Boolean(sku.is_active);
  const code = sku.sku_code || '';
  const [platform, warehouse, audit] = await Promise.allSettled([
    fetchPlatformProductDetails({ internal_sku_id: route.params.id, page: 1, page_size: 100 }),
    fetchWarehouseSkus({ search: code, page: 1, page_size: 100 }),
    fetchOperationLogs({ object_type: 'ProductSKU', object_id: String(route.params.id), page: 1, page_size: 50 }),
  ]);
  platformRows.value = platform.status === 'fulfilled' ? rowsOf(platform.value).filter(row => Number(row.internal_sku) === Number(route.params.id) || row.internal_sku_code === code) : [];
  warehouseRows.value = warehouse.status === 'fulfilled' ? rowsOf(warehouse.value).filter(row => Number(row.internal_sku_id) === Number(route.params.id) || row.internal_sku_code === code) : [];
  auditRows.value = audit.status === 'fulfilled' ? rowsOf(audit.value) : [];
  loading.value = false;
}

function calculateVolume() {
  const volume = Number(form.package_length_cm || 0) * Number(form.package_width_cm || 0) * Number(form.package_height_cm || 0) / 1000000;
  form.package_volume = Number(volume.toFixed(6));
}

async function save() {
  saving.value = true;
  const fields = ['product_name', 'purchase_price', 'unit', 'image_url', 'package_weight', 'package_volume', 'package_length_cm', 'package_width_cm', 'package_height_cm', 'origin_country', 'hs_code', 'material', 'inventory_type', 'selling_points', 'product_description'];
  const numericFields = new Set(['purchase_price', 'package_weight', 'package_volume', 'package_length_cm', 'package_width_cm', 'package_height_cm']);
  const payload = Object.fromEntries(fields.map(key => [key, numericFields.has(key) && form[key] === '' ? null : (form[key] ?? '')]));
  if (canEditLegacyCodes.value) payload.legacy_sku_code = String(form.legacy_sku_code || '').trim();
  const update = await updateProductSku(route.params.id, payload);
  if (!update.success) { ElMessage.error(update.message || '保存失败'); saving.value = false; return; }
  if (Boolean(form.is_active) !== originalActive.value) {
    const status = await updateProductSkuStatus(route.params.id, { is_active: Boolean(form.is_active) });
    if (!status.success) { ElMessage.error(status.message || '商品信息已保存，但状态修改失败'); saving.value = false; return; }
  }
  ElMessage.success('商品明细已保存');
  saving.value = false;
  await reload();
}

onMounted(reload);
</script>

<style scoped>
.sku-editor { min-height: calc(100vh - 64px); background: #f4f6f9; color: #1f2937; }
.editor-head { position: sticky; top: 0; z-index: 12; display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 16px 24px; background: #fff; border-bottom: 1px solid #e5e7eb; box-shadow: 0 2px 8px rgb(15 23 42 / 5%); }
.head-main,.head-actions { display: flex; align-items: center; gap: 14px; }.head-main h1 { margin: 2px 0 0; font-size: 21px; }.eyebrow { color: #64748b; font-size: 12px; }
.editor-layout { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 20px; max-width: 1440px; margin: 0 auto; padding: 22px 24px 60px; }
.anchor-nav { position: sticky; top: 100px; align-self: start; display: flex; flex-direction: column; padding: 16px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
.anchor-nav strong { margin-bottom: 10px; }.anchor-nav a { padding: 9px 8px; color: #475569; text-decoration: none; border-left: 2px solid transparent; }.anchor-nav a:hover { color: #2563eb; border-left-color: #2563eb; background: #eff6ff; }
.editor-main { min-width: 0; display: flex; flex-direction: column; gap: 16px; }.editor-card { scroll-margin-top: 96px; padding: 22px 24px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
.section-title { display: flex; align-items: baseline; gap: 14px; margin-bottom: 18px; }.section-title h2 { margin: 0; font-size: 18px; }.section-title span { color: #64748b; font-size: 13px; }
.basic-grid { display: grid; grid-template-columns: 180px 1fr; gap: 24px; }.image-box { height: 210px; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 8px; cursor: pointer; color: #94a3b8; border: 1px dashed #cbd5e1; border-radius: 8px; background: #f8fafc; }.image-box .el-image { width: 100%; height: 170px; }.image-box small { font-size: 12px; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 18px; }.span-2 { grid-column: span 2; }.compact-grid { max-width: 360px; }.measure-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 0 18px; }.volume-button { align-self: center; justify-self: start; }
.field-hint { margin-top: 6px; color: #909399; font-size: 12px; }
@media (max-width: 1100px) { .editor-layout { grid-template-columns: 1fr; }.anchor-nav { position: static; flex-direction: row; flex-wrap: wrap; }.basic-grid { grid-template-columns: 1fr; }.image-box { width: 180px; }.measure-grid { grid-template-columns: 1fr 1fr; } }
</style>
