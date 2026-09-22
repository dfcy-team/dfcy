<template>
  <section class="bundle-editor" v-loading="loading">
    <header class="editor-head">
      <div class="head-main">
        <el-button text @click="goBack">← 返回商品明细</el-button>
        <div><div class="eyebrow">组合商品编辑</div><h1>{{ form.sku_code || '组合商品' }}</h1></div>
        <el-tag type="warning" effect="plain">组合商品</el-tag>
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
        <el-alert title="组合商品由多个普通 SKU 组成。修改组成关系会创建新版本，历史订单仍使用下单时的组合快照。" type="warning" :closable="false" show-icon />

        <section id="bundle-basic" class="editor-card">
          <div class="section-title"><h2>组合商品信息</h2><span>维护组合商品自身的名称、图片和销售状态</span></div>
          <div class="basic-grid">
            <div class="image-box" @click="previewVisible = Boolean(form.image_url)">
              <el-image v-if="form.image_url" :src="imageSrc(form.image_url)" fit="contain" />
              <span v-else>暂无图片</span><small>{{ form.image_url ? '点击放大' : '填写图片链接后预览' }}</small>
            </div>
            <el-form label-position="top" class="form-grid">
              <el-form-item label="组合商品名称" class="span-2"><el-input v-model="form.product_name" maxlength="200" show-word-limit /></el-form-item>
              <el-form-item label="组合 SKU 编码"><el-input v-model="form.sku_code" disabled /></el-form-item>
              <el-form-item label="旧 SKU 编码">
                <el-input v-model="form.legacy_sku_code" :disabled="!canEditLegacyCodes" :placeholder="canEditLegacyCodes ? '请输入旧 SKU 编码' : '仅管理员可编辑'" />
              </el-form-item>
              <el-form-item label="所属组合 SPU"><el-input :model-value="bundleDetail.spu_code || String(form.spu || '')" disabled /></el-form-item>
              <el-form-item label="计量单位"><el-input v-model="form.unit" placeholder="如：套" /></el-form-item>
              <el-form-item label="销售状态"><el-switch v-model="form.is_active" active-text="在售" inactive-text="停用" /></el-form-item>
              <el-form-item label="图片链接" class="span-2"><el-input v-model="form.image_url" placeholder="https://... 或 /media/product-images/..." /></el-form-item>
            </el-form>
          </div>
        </section>

        <section id="bundle-components" class="editor-card">
          <div class="section-title section-title-actions">
            <div><h2>组合内容</h2><span>选择普通商品 SKU，并设置每套组合的使用数量</span></div>
            <el-button type="primary" plain :disabled="components.length >= 20" @click="components.push({ sku: null, quantity: 1 })">添加子商品</el-button>
          </div>
          <div class="component-head component-row"><span>子商品 SKU</span><span>商品名称</span><span>每套数量</span><span>操作</span></div>
          <div v-for="(item, index) in components" :key="`${index}-${item.sku}`" class="component-row">
            <el-select v-model="item.sku" filterable placeholder="搜索普通 SKU">
              <el-option v-for="sku in normalSkus" :key="sku.id" :label="`${sku.sku_code} ${sku.product_name || ''}`" :value="sku.id" />
            </el-select>
            <span>{{ skuName(item.sku) }}</span>
            <el-input-number v-model="item.quantity" :min="1" :precision="0" />
            <el-button link type="danger" :disabled="components.length <= 1" @click="components.splice(index, 1)">删除</el-button>
          </div>
          <el-form label-position="top" class="version-form">
            <el-form-item label="组合关系变更原因" :required="componentsChanged">
              <el-input v-model="changeReason" type="textarea" :rows="2" :placeholder="componentsChanged ? '组成关系变化时必须填写，用于版本审计' : '组成关系未变化时无需填写'" />
            </el-form-item>
            <el-form-item v-if="componentsChanged" label="生效时间" required><el-date-picker v-model="effectiveAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
          </el-form>
        </section>

        <section id="bundle-price" class="editor-card">
          <div class="section-title"><h2>价格与包装</h2><span>维护组合商品整体采购成本和发货包装</span></div>
          <el-form label-position="top" class="measure-grid">
            <el-form-item label="组合采购价"><el-input-number v-model="form.purchase_price" :min="0" :precision="4" /></el-form-item>
            <el-form-item label="包装重量 (g)"><el-input-number v-model="form.package_weight" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="长 (cm)"><el-input-number v-model="form.package_length_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="宽 (cm)"><el-input-number v-model="form.package_width_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="高 (cm)"><el-input-number v-model="form.package_height_cm" :min="0" :precision="3" /></el-form-item>
            <el-form-item label="包装体积 (m³)"><el-input-number v-model="form.package_volume" :min="0" :precision="6" /></el-form-item>
          </el-form>
        </section>

        <section id="bundle-mapping" class="editor-card">
          <div class="section-title"><h2>平台 SKU 映射</h2><span>组合商品在各平台和店铺的映射关系</span></div>
          <el-table :data="platformRows" empty-text="暂无平台 SKU 映射">
            <el-table-column prop="platform_name" label="平台" width="120" /><el-table-column prop="store_name" label="店铺" min-width="150" />
            <el-table-column prop="title" label="平台商品" min-width="210" show-overflow-tooltip /><el-table-column prop="platform_product_id" label="Item ID" min-width="140" />
            <el-table-column prop="platform_sku" label="平台 SKU" min-width="150" /><el-table-column label="映射状态" width="110"><template #default="{ row }"><el-tag size="small" :type="row.mapping ? 'success' : 'info'">{{ row.mapping ? '已映射' : '待确认' }}</el-tag></template></el-table-column>
          </el-table>
        </section>

        <section id="bundle-inventory" class="editor-card">
          <div class="section-title"><h2>组合库存</h2><span>按仓库中各子 SKU 的可用量计算最大可组套数量</span></div>
          <el-table :data="availabilityRows" empty-text="暂无组合库存快照">
            <el-table-column prop="warehouse_name" label="仓库" min-width="160" /><el-table-column prop="available_quantity" label="可组套数量" width="130" align="right" />
            <el-table-column label="子商品库存明细" min-width="360"><template #default="{ row }">{{ availabilitySummary(row) }}</template></el-table-column>
          </el-table>
        </section>

        <section id="bundle-history" class="editor-card">
          <div class="section-title"><h2>版本与修改记录</h2><span>组合关系版本和商品字段操作记录</span></div>
          <el-table :data="bundleDetail.versions || []" empty-text="暂无组合版本">
            <el-table-column prop="version" label="版本" width="80" /><el-table-column prop="effective_at" label="生效时间" min-width="180" />
            <el-table-column prop="reason" label="变更原因" min-width="220" /><el-table-column prop="created_at" label="创建时间" min-width="180" />
          </el-table>
          <el-divider />
          <el-table :data="auditRows" empty-text="暂无修改记录">
            <el-table-column prop="created_at" label="时间" min-width="180" /><el-table-column prop="operator_name" label="操作人" width="130" />
            <el-table-column prop="action" label="操作" width="160" /><el-table-column prop="module" label="模块" min-width="140" />
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
import { fetchProductBundleAvailability, fetchProductBundleDetail, fetchProductSku, fetchProductSkuList, updateProductBundle, updateProductSku, updateProductSkuStatus } from '../../api/products';
import { fetchPlatformProductDetails } from '../../api/platformProductDetails';
import { fetchOperationLogs } from '../../api/audit';
import { apiBaseUrl } from '../../api/baseUrl';
import { collectionRows, detailData } from '../../utils/businessResponse';
import { useAuthStore } from '../../stores/auth';

const route = useRoute(); const router = useRouter(); const auth = useAuthStore();
const loading = ref(false); const saving = ref(false); const previewVisible = ref(false);
const form = reactive({}); const bundleDetail = reactive({ versions: [] });
const components = ref([]); const originalComponents = ref('[]'); const normalSkus = ref([]);
const platformRows = ref([]); const availabilityRows = ref([]); const auditRows = ref([]);
const changeReason = ref(''); const effectiveAt = ref(''); const originalActive = ref(true);
const canEditLegacyCodes = computed(() => Boolean(auth.currentUser?.is_superuser || auth.currentUser?.roles?.includes('administrator')));
const anchors = [
  { id: 'bundle-basic', label: '组合商品信息' }, { id: 'bundle-components', label: '组合内容' },
  { id: 'bundle-price', label: '价格与包装' }, { id: 'bundle-mapping', label: '平台 SKU 映射' },
  { id: 'bundle-inventory', label: '组合库存' }, { id: 'bundle-history', label: '版本与修改记录' },
];
const normalizedComponents = computed(() => components.value.map((item) => ({ component_sku: Number(item.sku), quantity: Number(item.quantity) })));
const componentsChanged = computed(() => JSON.stringify(normalizedComponents.value) !== originalComponents.value);
const rowsOf = (response) => collectionRows(response?.data);
const imageSrc = (url) => !url || /^https?:/i.test(url) ? url : `${apiBaseUrl}${url}`;
const goBack = () => router.push({ path: '/products/details', query: { product_type: 'bundle' } });
const componentId = (row) => row.component_sku_id ?? row.component_sku?.id ?? row.component_sku;
const skuName = (id) => normalSkus.value.find((sku) => Number(sku.id) === Number(id))?.product_name || '-';
const availabilitySummary = (row) => (row.components || []).map((item) => `${item.component_sku_code}：${item.available_quantity} / 每套${item.required_quantity}`).join('；') || '-';
const currentIsoMinute = () => { const date = new Date(); date.setSeconds(0, 0); return date.toISOString(); };

async function reload() {
  loading.value = true;
  try {
    const skuResponse = await fetchProductSku(route.params.id);
    const detailResponse = await fetchProductBundleDetail(route.params.id);
    if (!skuResponse.success || !detailResponse.success) throw new Error(skuResponse.message || detailResponse.message || '组合商品加载失败');
    const sku = detailData(skuResponse.data) || {}; const detail = detailData(detailResponse.data) || {};
    if (sku.product_type && sku.product_type !== 'bundle') { await router.replace(`/products/details/${route.params.id}/edit`); return; }
    Object.assign(form, sku); Object.assign(bundleDetail, detail);
    const nextComponents = (detail.components || []).map((item) => ({ sku: Number(componentId(item)), quantity: Number(item.quantity || 1) }));
    components.value = nextComponents.length ? nextComponents : [{ sku: null, quantity: 1 }];
    originalComponents.value = JSON.stringify(nextComponents.map((item) => ({ component_sku: item.sku, quantity: item.quantity })));
    originalActive.value = Boolean(sku.is_active); changeReason.value = ''; effectiveAt.value = currentIsoMinute();
    const code = sku.sku_code || '';
    const [skuList, platform, availability, audit] = await Promise.allSettled([
      fetchProductSkuList({ product_type: 'standard', page: 1, page_size: 100 }),
      fetchPlatformProductDetails({ internal_sku_id: route.params.id, page: 1, page_size: 100 }),
      fetchProductBundleAvailability(route.params.id),
      fetchOperationLogs({ object_type: 'ProductSKU', object_id: String(route.params.id), page: 1, page_size: 50 }),
    ]);
    normalSkus.value = skuList.status === 'fulfilled' ? rowsOf(skuList.value).filter((item) => item.product_type !== 'bundle') : [];
    platformRows.value = platform.status === 'fulfilled' ? rowsOf(platform.value).filter((item) => Number(item.internal_sku) === Number(route.params.id) || item.internal_sku_code === code) : [];
    availabilityRows.value = availability.status === 'fulfilled' ? (detailData(availability.value.data)?.warehouses || []) : [];
    auditRows.value = audit.status === 'fulfilled' ? rowsOf(audit.value) : [];
  } catch (error) { ElMessage.error(error?.message || '组合商品加载失败'); }
  finally { loading.value = false; }
}

async function save() {
  if (!components.value.length || components.value.some((item) => !item.sku || !Number.isInteger(Number(item.quantity)) || Number(item.quantity) < 1)) { ElMessage.warning('请完整填写组合子商品和每套数量'); return; }
  if (new Set(components.value.map((item) => Number(item.sku))).size !== components.value.length) { ElMessage.warning('同一子商品不能重复添加'); return; }
  if (componentsChanged.value && (!changeReason.value.trim() || !effectiveAt.value)) { ElMessage.warning('修改组合内容时必须填写变更原因和生效时间'); return; }
  saving.value = true;
  try {
    const fields = ['product_name', 'purchase_price', 'unit', 'image_url', 'package_weight', 'package_volume', 'package_length_cm', 'package_width_cm', 'package_height_cm'];
    const numeric = new Set(['purchase_price', 'package_weight', 'package_volume', 'package_length_cm', 'package_width_cm', 'package_height_cm']);
    const payload = Object.fromEntries(fields.map((key) => [key, numeric.has(key) && form[key] === '' ? null : (form[key] ?? '')]));
    if (canEditLegacyCodes.value) payload.legacy_sku_code = String(form.legacy_sku_code || '').trim();
    const basic = await updateProductSku(route.params.id, payload); if (!basic.success) throw new Error(basic.message || '组合商品信息保存失败');
    if (componentsChanged.value) {
      const relation = await updateProductBundle(route.params.id, { effective_at: effectiveAt.value, reason: changeReason.value.trim(), components: normalizedComponents.value });
      if (!relation.success) throw new Error(relation.message || '组合内容保存失败');
    }
    if (Boolean(form.is_active) !== originalActive.value) {
      const status = await updateProductSkuStatus(route.params.id, { is_active: Boolean(form.is_active), reason: '组合商品编辑页手动调整状态' });
      if (!status.success) throw new Error(status.message || '商品状态更新失败');
    }
    ElMessage.success('组合商品已保存'); await reload();
  } catch (error) { ElMessage.error(error?.message || '保存失败'); }
  finally { saving.value = false; }
}

onMounted(reload);
</script>

<style scoped>
.bundle-editor{min-height:calc(100vh - 64px);background:#f4f6f9;color:#1f2937}.editor-head{position:sticky;top:0;z-index:12;display:flex;justify-content:space-between;align-items:center;gap:24px;padding:16px 24px;background:#fff;border-bottom:1px solid #e5e7eb;box-shadow:0 2px 8px rgb(15 23 42 / 5%)}.head-main,.head-actions{display:flex;align-items:center;gap:14px}.head-main h1{margin:2px 0 0;font-size:21px}.eyebrow{color:#64748b;font-size:12px}.editor-layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:20px;max-width:1480px;margin:0 auto;padding:22px 24px 60px}.anchor-nav{position:sticky;top:100px;align-self:start;display:flex;flex-direction:column;padding:16px;background:#fff;border:1px solid #e5e7eb;border-radius:8px}.anchor-nav strong{margin-bottom:10px}.anchor-nav a{padding:9px 8px;color:#475569;text-decoration:none;border-left:2px solid transparent}.anchor-nav a:hover{color:#d97706;border-left-color:#d97706;background:#fffbeb}.editor-main{min-width:0;display:flex;flex-direction:column;gap:16px}.editor-card{scroll-margin-top:96px;padding:22px 24px;background:#fff;border:1px solid #e5e7eb;border-radius:8px}.section-title{display:flex;align-items:baseline;gap:14px;margin-bottom:18px}.section-title h2{margin:0;font-size:18px}.section-title span{color:#64748b;font-size:13px}.section-title-actions{justify-content:space-between}.section-title-actions>div{display:flex;align-items:baseline;gap:14px}.basic-grid{display:grid;grid-template-columns:180px 1fr;gap:24px}.image-box{height:210px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:8px;cursor:pointer;color:#94a3b8;border:1px dashed #cbd5e1;border-radius:8px;background:#f8fafc}.image-box .el-image{width:100%;height:170px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px}.span-2{grid-column:span 2}.component-row{display:grid;grid-template-columns:minmax(240px,1.3fr) minmax(180px,1fr) 130px 70px;gap:14px;align-items:center;padding:10px 12px;border-bottom:1px solid #eef2f7}.component-head{color:#64748b;font-size:13px;font-weight:600;background:#f8fafc}.version-form{margin-top:20px;max-width:760px}.measure-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 18px}@media(max-width:1100px){.editor-layout{grid-template-columns:1fr}.anchor-nav{position:static;flex-direction:row;flex-wrap:wrap}.basic-grid{grid-template-columns:1fr}.image-box{width:180px}.measure-grid{grid-template-columns:1fr 1fr}.component-row{grid-template-columns:1fr 1fr}}
</style>
