<template>
  <AppPage
    title="全球刊登工作台"
    eyebrow="全球刊登"
    subtitle="选择商品、店铺、模板和 SKU，生成当前租户范围内的刊登草稿。"
    boundary-note="发布仅创建内部 API/RPA 任务，不代表已接通外部平台。"
    capability="connected"
  >
    <el-form label-position="top" class="selection-form">
      <el-form-item label="SPU" required>
        <el-select v-model="form.spu_ids" multiple filterable collapse-tags style="width: 100%">
          <el-option v-for="item in options.spus" :key="item.id" :value="item.id" :label="`${item.spu_code || item.id} - ${item.product_name || ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标店铺" required>
        <el-select v-model="form.store_ids" multiple filterable collapse-tags style="width: 100%">
          <el-option v-for="item in options.stores" :key="item.id" :value="item.id" :label="`${item.name || item.code || item.id} - ${item.country_code || ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="刊登模板">
        <el-select v-model="form.template_id" clearable filterable style="width: 100%">
          <el-option v-for="item in options.templates" :key="item.id" :value="item.id" :label="`${item.name || item.template_no} - ${item.platform_name || item.platform_code || item.platform || ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="SKU（留空表示所选 SPU 的全部 SKU）">
        <el-select v-model="form.sku_ids" multiple filterable collapse-tags style="width: 100%">
          <el-option v-for="item in filteredSkus" :key="item.id" :value="item.id" :label="`${item.sku_code || item.id} - ${item.color_code || ''} - ${item.specification || ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="loading" @click="generate">生成刊登草稿</el-button>
        <el-button :loading="loadingOptions" @click="load">刷新选项</el-button>
      </el-form-item>
    </el-form>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-table v-if="drafts.length" :data="drafts" border class="result-table">
      <el-table-column prop="profile_no" label="资料编号" width="180" />
      <el-table-column label="SPU" min-width="180"><template #default="{ row }">{{ row.spu_code || row.product_name || row.product }}</template></el-table-column>
      <el-table-column label="店铺" min-width="150"><template #default="{ row }">{{ row.store_name || row.store }} {{ row.country_code || '' }}</template></el-table-column>
      <el-table-column label="SKU 数" width="90"><template #default="{ row }">{{ row.variants?.length || 0 }}</template></el-table-column>
      <el-table-column prop="status" label="状态" width="130" />
      <el-table-column label="详情" width="100"><template #default="{ row }"><router-link :to="`/listings/sites/${row.id}`">查看</router-link></template></el-table-column>
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
const drafts = ref([]); const loading = ref(false); const loadingOptions = ref(false); const error = ref('');
const filteredSkus = computed(() => options.skus.filter((sku) => !form.spu_ids.length || form.spu_ids.includes(sku.spu_id)));
function rows(response, key) { return response?.data?.[key] || []; }
async function load() {
  loadingOptions.value = true; error.value = '';
  const response = await fetchListingWorkbenchOptions();
  loadingOptions.value = false;
  if (!response.success) { error.value = response.message || '加载工作台选项失败'; return; }
  options.spus = rows(response, 'spus'); options.skus = rows(response, 'skus'); options.stores = rows(response, 'stores'); options.templates = rows(response, 'templates');
}
async function generate() {
  if (!form.spu_ids.length || !form.store_ids.length) return ElMessage.warning('请至少选择一个 SPU 和一个店铺。');
  loading.value = true; error.value = '';
  const response = await batchGenerateListingDrafts({ ...form }, `listing-drafts-${Date.now()}`);
  loading.value = false;
  if (!response.success) { error.value = response.message || '生成刊登草稿失败'; return; }
  drafts.value = response.data?.items || []; ElMessage.success(`已生成 ${drafts.value.length} 条刊登草稿。`);
}
onMounted(load);
</script>

<style scoped>
.selection-form { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 4px 18px; padding: 18px; background: #fff; border: 1px solid #dbe3ec; border-radius: 8px; }
.selection-form .form-actions { grid-column: 1 / -1; }
.result-table { margin-top: 16px; }
@media (max-width: 760px) { .selection-form { grid-template-columns: 1fr; } .selection-form .form-actions { grid-column: auto; } }
</style>
