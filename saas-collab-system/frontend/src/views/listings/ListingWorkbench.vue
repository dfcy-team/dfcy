<template>
  <AppPage title="全球刊登工作台" eyebrow="GLOBAL LISTING" subtitle="选择 SPU、店铺、模板和 SKU，一次生成租户内的刊登草稿。" boundary-note="发布任务仅进入内部 API/RPA 队列；系统不会宣称已接通任何外部平台。" capability="connected">
    <el-form label-position="top" class="selection-form">
      <el-form-item label="商品 SPU" required>
        <el-select v-model="form.spu_ids" multiple filterable collapse-tags style="width:100%" placeholder="选择 SPU">
          <el-option v-for="item in options.spus" :key="item.id" :value="item.id" :label="`${item.spu_code} · ${item.product_name}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标店铺" required>
        <el-select v-model="form.store_ids" multiple filterable collapse-tags style="width:100%" placeholder="选择店铺">
          <el-option v-for="item in options.stores" :key="item.id" :value="item.id" :label="`${item.name} · ${item.country_code}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="刊登模板">
        <el-select v-model="form.template_id" clearable filterable style="width:100%" placeholder="可选：按店铺平台筛选">
          <el-option v-for="item in options.templates" :key="item.id" :value="item.id" :label="`${item.name} · ${item.platform_name || item.platform_code || item.platform}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="SKU（留空则使用所选 SPU 的全部启用 SKU）">
        <el-select v-model="form.sku_ids" multiple filterable collapse-tags style="width:100%" placeholder="可选 SKU">
          <el-option v-for="item in filteredSkus" :key="item.id" :value="item.id" :label="`${item.sku_code} · ${item.color_code || '无颜色'} · ${item.specification || '无规格'}`" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" @click="generate">批量生成草稿</el-button><el-button @click="load">刷新选项</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-table v-if="drafts.length" :data="drafts" border class="result-table">
      <el-table-column prop="profile_no" label="资料编号" width="180" />
      <el-table-column label="SPU" min-width="180"><template #default="{row}">{{ row.spu_code }} / {{ row.legacy_spu_code || '无旧编码' }}</template></el-table-column>
      <el-table-column label="店铺" min-width="150"><template #default="{row}">{{ row.store_name }} · {{ row.country_code }}</template></el-table-column>
      <el-table-column label="SKU 数" width="100"><template #default="{row}">{{ row.variants?.length || 0 }}</template></el-table-column>
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column label="操作" width="100"><template #default="{row}"><router-link :to="`/listings/sites/${row.id}`">编辑</router-link></template></el-table-column>
    </el-table>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { batchGenerateListingDrafts, fetchListingWorkbenchOptions } from '../../api/listings';

const options = reactive({ spus: [], skus: [], stores: [], templates: [] });
const form = reactive({ spu_ids: [], store_ids: [], template_id: null, sku_ids: [] });
const drafts = ref([]); const loading = ref(false); const error = ref('');
const filteredSkus = computed(() => options.skus.filter((sku) => !form.spu_ids.length || form.spu_ids.includes(sku.spu_id)));
function unpack(response, key) { return response?.data?.[key] || []; }
async function load() {
  const response = await fetchListingWorkbenchOptions();
  if (!response.success) { error.value = response.message || '工作台选项加载失败'; return; }
  options.spus = unpack(response, 'spus'); options.skus = unpack(response, 'skus'); options.stores = unpack(response, 'stores'); options.templates = unpack(response, 'templates');
}
async function generate() {
  if (!form.spu_ids.length || !form.store_ids.length) return ElMessage.warning('请选择至少一个 SPU 和店铺');
  loading.value = true; error.value = '';
  const response = await batchGenerateListingDrafts({ ...form }, `listing-drafts-${Date.now()}`);
  loading.value = false;
  if (!response.success) { error.value = response.message || '草稿生成失败'; return; }
  drafts.value = response.data?.items || []; ElMessage.success(`已生成 ${drafts.value.length} 条草稿`);
}
onMounted(load);
</script>

<style scoped>
.selection-form { display:grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 4px 18px; padding: 18px; background:#fff; border:1px solid #dbe3ec; border-radius:8px; }
.selection-form .el-form-item:last-child { grid-column:1/-1; }
.result-table { margin-top:16px; }
@media (max-width: 760px) { .selection-form { grid-template-columns:1fr; } .selection-form .el-form-item:last-child { grid-column:auto; } }
</style>
