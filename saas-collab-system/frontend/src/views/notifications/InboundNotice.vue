<template>
  <main class="notice-page">
    <el-card v-loading="loading" shadow="never" class="notice-card">
      <template #header>
        <div class="page-heading">
          <div>
            <p class="eyebrow">到货通知</p>
            <h1>{{ notice?.number || '通知详情' }}</h1>
          </div>
          <el-tag v-if="notice" type="info">只读</el-tag>
        </div>
      </template>

      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
      <template v-else-if="notice">
        <section class="summary-grid" aria-label="到货摘要">
          <div><span>批次</span><strong>{{ display(notice.batch_number) }}</strong></div>
          <div><span>国家</span><strong>{{ display(notice.country_label) }}</strong></div>
          <div><span>仓库</span><strong>{{ display(notice.warehouse_name) }}</strong></div>
          <div><span>确认时间</span><strong>{{ displayDate(notice.confirmed_at) }}</strong></div>
          <div><span>发货总数</span><strong>{{ display(notice.expected_quantity) }}</strong></div>
          <div><span>实收总数</span><strong>{{ display(notice.received_quantity) }}</strong></div>
          <div><span>差异</span><strong>{{ display(notice.difference) }}</strong></div>
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><h2>到货明细</h2><p>共 {{ filteredItems.length }} 项</p></div>
            <el-input v-model="itemSearch" class="search-input" clearable placeholder="搜索产品名称或编码" aria-label="搜索到货明细" />
          </div>
          <el-table :data="pagedItems" border stripe empty-text="没有匹配的到货明细">
            <el-table-column prop="product_name" label="产品" min-width="190" show-overflow-tooltip />
            <el-table-column label="SKU 编码" min-width="220">
              <template #default="{ row }"><div class="codes"><span><b>新</b>{{ display(row.sku_code) }}</span><span><b>旧</b>{{ display(row.legacy_sku_code) }}</span></div></template>
            </el-table-column>
            <el-table-column prop="expected_quantity" label="发货" width="90" align="right" />
            <el-table-column prop="received_quantity" label="实收" width="90" align="right" />
            <el-table-column prop="difference" label="差异" width="90" align="right" />
            <el-table-column label="类型" width="100"><template #default="{ row }">{{ row.is_extra ? '额外到货' : '发货商品' }}</template></el-table-column>
          </el-table>
          <el-pagination v-if="filteredItems.length" v-model:current-page="itemPage" v-model:page-size="itemPageSize" class="pagination" :page-sizes="[10, 20, 50]" :total="filteredItems.length" layout="total, sizes, prev, pager, next" />
        </section>

        <section class="content-section transit-section">
          <div class="section-heading">
            <div><h2>同国在途款式预告</h2><p>截至 {{ displayDate(notice.preview_as_of) }}</p></div>
            <el-input v-model="transitSearch" class="search-input" clearable placeholder="搜索款式名称或编码" aria-label="搜索在途款式" />
          </div>
          <el-table :data="pagedTransitStyles" border stripe empty-text="暂无匹配的在途款式">
            <el-table-column prop="product_name" label="款式" min-width="190" show-overflow-tooltip />
            <el-table-column label="SPU 编码" min-width="220">
              <template #default="{ row }"><div class="codes"><span><b>新</b>{{ display(row.spu_code) }}</span><span><b>旧</b>{{ display(row.legacy_spu_code) }}</span></div></template>
            </el-table-column>
          </el-table>
          <el-pagination v-if="filteredTransitStyles.length" v-model:current-page="transitPage" v-model:page-size="transitPageSize" class="pagination" :page-sizes="[10, 20, 50]" :total="filteredTransitStyles.length" layout="total, sizes, prev, pager, next" />
        </section>
      </template>
    </el-card>
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { requestApi } from '../../api/request';

const route = useRoute();
const loading = ref(true);
const error = ref('');
const notice = ref(null);
const itemSearch = ref('');
const transitSearch = ref('');
const itemPage = ref(1);
const transitPage = ref(1);
const itemPageSize = ref(10);
const transitPageSize = ref(10);
const display = (value) => value === null || value === undefined || value === '' ? '未维护' : value;
const displayDate = (value) => value ? new Date(value).toLocaleString() : '未维护';
const filteredItems = computed(() => {
  const needle = itemSearch.value.trim().toLocaleLowerCase();
  return (notice.value?.items || []).filter((item) => !needle || [item.product_name, item.sku_code, item.legacy_sku_code].some((value) => String(value || '').toLocaleLowerCase().includes(needle)));
});
const filteredTransitStyles = computed(() => {
  const needle = transitSearch.value.trim().toLocaleLowerCase();
  return (notice.value?.transit_styles || []).filter((item) => !needle || [item.product_name, item.spu_code, item.legacy_spu_code].some((value) => String(value || '').toLocaleLowerCase().includes(needle)));
});
const pagedItems = computed(() => filteredItems.value.slice((itemPage.value - 1) * itemPageSize.value, itemPage.value * itemPageSize.value));
const pagedTransitStyles = computed(() => filteredTransitStyles.value.slice((transitPage.value - 1) * transitPageSize.value, transitPage.value * transitPageSize.value));
watch(itemSearch, () => { itemPage.value = 1; });
watch(transitSearch, () => { transitPage.value = 1; });
watch(itemPageSize, () => { itemPage.value = 1; });
watch(transitPageSize, () => { transitPage.value = 1; });

watch(() => route.params.id, async (id) => {
  loading.value = true;
  error.value = '';
  notice.value = null;
  const result = await requestApi({ method: 'get', url: `/api/internal/supply-chain/v2/inbound-notices/${encodeURIComponent(id)}/`, noMockFallback: true });
  loading.value = false;
  if (!result?.success || !result.data || typeof result.data !== 'object') {
    error.value = result?.http_status === 404 ? '找不到这条到货通知。' : result?.message || '加载到货通知失败，请稍后重试。';
    return;
  }
  notice.value = result.data;
}, { immediate: true });
</script>

<style scoped>
.notice-page { max-width: 1180px; margin: 0 auto; padding: 20px; color: #1d2939; }
.notice-card { border: 1px solid #e8edf3; border-radius: 14px; }
.page-heading, .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.eyebrow { margin: 0 0 6px; color: #64748b; font-size: 12px; }
h1 { margin: 0; font-size: 23px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.summary-grid > div { display: flex; min-height: 68px; flex-direction: column; justify-content: center; gap: 7px; padding: 12px; border-radius: 10px; background: #f7f9fc; }
.summary-grid span, .section-heading p { color: #64748b; font-size: 12px; }
.summary-grid strong { overflow-wrap: anywhere; font-size: 14px; }
.content-section { margin-top: 30px; }
.section-heading { margin-bottom: 12px; }
h2 { margin: 0; font-size: 17px; }
.section-heading p { margin: 5px 0 0; }
.search-input { max-width: 280px; }
.codes { display: grid; gap: 5px; }
.codes span { overflow-wrap: anywhere; }
.codes b { display: inline-block; width: 26px; margin-right: 6px; color: #64748b; font-size: 11px; }
.pagination { justify-content: flex-end; margin-top: 14px; }
@media (max-width: 700px) { .notice-page { padding: 12px; } .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .section-heading { align-items: flex-start; flex-direction: column; } .search-input { max-width: none; width: 100%; } .pagination { justify-content: flex-start; flex-wrap: wrap; gap: 8px; } }
</style>
