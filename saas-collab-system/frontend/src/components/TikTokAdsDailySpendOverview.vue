<template>
  <AppPage title="TikTok 广告已存数据" capability="只读已存数据"
    subtitle="默认查看马尼拉时间最近 7 个完整自然日；查询不会触发采集。"
    boundary-note="GMV Max 快照与 BASIC/AUCTION_CAMPAIGN 分开展示，不代表全部广告。缺失数据不是零消耗；不同币种不合并。">
    <el-form inline class="filters" @submit.prevent="load(1)">
      <el-form-item label="开始日期"><el-date-picker v-model="from" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="结束日期"><el-date-picker v-model="to" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="店铺">
        <el-select v-model="store" clearable placeholder="全部可见店铺" class="subject-select">
          <el-option v-for="item in stores" :key="item.store_id" :value="item.store_id" :label="item.store_code + ' ' + item.store_name" />
        </el-select>
      </el-form-item>
      <el-form-item label="广告账户">
        <el-select v-model="advertiser" clearable placeholder="全部可见广告账户" class="subject-select">
          <el-option v-for="item in advertisers" :key="item.mapping_id" :value="item.advertiser_id" :label="item.store_code + ' · ' + (item.advertiser_name || item.advertiser_id)" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" @click="load(1)">查询已存数据</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="report">
      <h2>GMV Max 已存单日快照</h2>
      <p>仅展示已采集快照，不触发同步；不与下方 BASIC 消耗或商城 GMV 合计，不同币种分开查看。</p>
      <el-table :data="report.gmv_max_snapshots || []" border :empty-text="report.gmv_max_snapshots === null ? 'GMV Max 快照过多，缩小日期范围或店铺后重试；当前不显示金额。' : '尚无 GMV Max 快照，不代表零消耗。'">
        <el-table-column prop="date" label="日期" />
        <el-table-column prop="store_code" label="店铺" />
        <el-table-column prop="advertiser_name" label="广告户名称" />
        <el-table-column prop="advertiser_id" label="广告主 ID" min-width="180" />
        <el-table-column prop="currency" label="币种" />
        <el-table-column prop="cost" label="消耗" />
        <el-table-column prop="gross_revenue" label="报表收入" />
        <el-table-column prop="orders" label="报表订单" />
        <el-table-column prop="campaign_count" label="计划数" />
        <el-table-column prop="timezone" label="报表时区" />
      </el-table>
      <h2>BASIC 竞价广告日消耗</h2>
      <el-alert v-for="warning in report.warnings" :key="warning" :title="warningLabels[warning] || warning" type="warning" :closable="false" show-icon class="notice" />
      <el-table :data="report.selected_subjects" border class="notice" empty-text="无可见账户">
        <el-table-column prop="store_code" label="店铺" />
        <el-table-column prop="advertiser_id" label="广告账户" min-width="180" />
        <el-table-column prop="advertiser_name" label="广告户名称" min-width="160" />
        <el-table-column label="采集开关（当前）"><template #default="{ row }"><el-tag :type="row.collection_enabled ? 'success' : 'info'">{{ row.collection_enabled ? '已开启' : '已关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="本地绑定证据"><template #default="{ row }">{{ row.local_evidence === 'verified' ? '已核验' : '未核验' }}</template></el-table-column>
      </el-table>
      <p>应覆盖映射日 {{ report.coverage.mapping_days }}；已存 {{ report.coverage.stored }}；缺失 {{ report.coverage.missing }}；明确零消耗 {{ report.coverage.explicit_zero }}。汇总覆盖全部分页。</p>
      <p>币种覆盖按当前映射元数据计算；历史事实金额始终保留事实币种。</p>
      <el-table :data="report.totals" border empty-text="无可见映射，总额未知" class="notice">
        <el-table-column prop="currency" label="币种" />
        <el-table-column label="总额"><template #default="{ row }">{{ row.total ?? '未知' }}</template></el-table-column>
        <el-table-column label="已知小计"><template #default="{ row }">{{ row.known_subtotal ?? '未知 / 未采集' }}</template></el-table-column>
        <el-table-column prop="expected_days" label="应覆盖映射日" />
        <el-table-column prop="stored_days" label="已存事实日" />
        <el-table-column prop="missing_days" label="缺失同币种日" />
        <el-table-column prop="explicit_zero" label="明确零消耗日" />
      </el-table>
      <el-table :data="report.results" border empty-text="无已存事实，不表示零消耗。">
        <el-table-column prop="date" label="日期" min-width="120" />
        <el-table-column prop="store_code" label="店铺" min-width="100" />
        <el-table-column prop="advertiser_id" label="广告账户" min-width="180" />
        <el-table-column prop="spend" label="消耗" min-width="140" />
        <el-table-column prop="currency" label="事实币种" />
        <el-table-column label="币种提示" min-width="160"><template #default="{ row }">{{ row.currency_mismatch ? '与当前映射币种不同' : '' }}</template></el-table-column>
        <el-table-column prop="fetched_at" label="采集时间" min-width="220" />
        <el-table-column prop="mapping_timezone" label="映射时区（当前元数据）" min-width="210" />
      </el-table>
      <el-pagination class="pagination" layout="prev, pager, next, total" :current-page="report.page"
        :page-size="report.page_size" :total="report.count" :disabled="loading" @current-change="load" />
    </template>
    <el-empty v-else-if="!loading && !error" description="请选择范围后查询已存数据" />
  </AppPage>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import AppPage from './AppPage.vue';
import { fetchTikTokDailySpend } from '../api/advertising';

const props = defineProps({ active: { type: Boolean, default: false } });
const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Manila', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
const part = (name) => parts.find((item) => item.type === name).value;
const today = Date.parse(part('year') + '-' + part('month') + '-' + part('day') + 'T00:00:00Z');
const from = ref(new Date(today - 7 * 86400000).toISOString().slice(0, 10));
const to = ref(new Date(today - 86400000).toISOString().slice(0, 10));
const store = ref('');
const advertiser = ref('');
const subjects = ref([]);
const stores = computed(() => [...new Map(subjects.value.map((item) => [item.store_id, item])).values()]);
const advertisers = computed(() => subjects.value.filter((item) => !store.value || item.store_id === store.value));
const loading = ref(false);
const error = ref('');
const report = ref(null);
const warningLabels = {
  collection_disabled: '部分账户采集开关已关闭，历史数据仍可查看。',
  local_evidence_unverified: '部分账户的当前本地绑定证据未核验；这不影响读取历史事实，也不代表实时授权有效。',
  fact_currency_differs_from_current_mapping: '存在事实币种与当前映射币种不一致的数据；保留原币种，不折算、不重新归类。',
  gmv_max_snapshot_limit_exceeded: 'GMV Max 快照数量超过读取上限，已跳过该部分；BASIC 报告仍可查看。请缩小日期范围或店铺。',
};
let sequence = 0;
let appliedQuery;
function invalidate() {
  sequence += 1;
  report.value = null;
  error.value = '';
  loading.value = false;
}
watch(store, () => { advertiser.value = ''; }, { flush: 'sync' });
watch([from, to, store, advertiser], invalidate, { flush: 'sync' });
watch(() => props.active, (active) => {
  invalidate();
  subjects.value = [];
  if (active) load(1);
}, { immediate: true });
onBeforeUnmount(invalidate);

async function load(page = 1) {
  if (!props.active) return;
  invalidate();
  const requestSequence = sequence;
  if (page === 1) {
    const days = (Date.parse(to.value) - Date.parse(from.value)) / 86400000;
    if (!Number.isFinite(days) || days < 0 || days >= 31) {
      error.value = '请选择明确的 1 至 31 天日期范围。';
      return;
    }
    appliedQuery = { date_from: from.value, date_to: to.value,
      ...(store.value ? { store_id: store.value } : {}),
      ...(advertiser.value ? { advertiser_id: advertiser.value } : {}) };
  }
  loading.value = true;
  try {
    const response = await fetchTikTokDailySpend({ ...appliedQuery, page, page_size: 50 });
    if (requestSequence !== sequence || !props.active) return;
    if (!response.success) throw new Error(response.message || '读取失败');
    report.value = response.data;
    subjects.value = response.data.subjects;
  } catch (failure) {
    if (requestSequence !== sequence || !props.active) return;
    subjects.value = [];
    error.value = failure?.response?.data?.message || failure.message || '读取失败，无模拟数据回退。';
  } finally {
    if (requestSequence === sequence) loading.value = false;
  }
}
</script>

<style scoped>
.filters { margin: 16px 0; }
.subject-select { width: 240px; }
.notice { margin-bottom: 16px; }
.pagination { margin-top: 16px; }
@media (max-width: 720px) { .subject-select { width: 100%; } }
</style>
