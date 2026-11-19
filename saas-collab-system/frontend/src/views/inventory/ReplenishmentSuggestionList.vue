<template>
  <AppPage title="补货建议" subtitle="按国家查询每日补货快照，按 SPU 汇总并展开查看 SKU。">
    <p class="muted">查询和翻页读取最近完整快照。</p>
    <el-select v-model="countryId" filterable placeholder="选择国家" aria-label="补货建议国家" style="width:230px">
      <el-option v-for="country in countries" :key="country.id" :value="country.id" :label="`${country.name} (${country.country_code || country.code || ''})`" />
    </el-select>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <OperatingReferenceV2 v-if="countryId" :key="countryId" :floating-basket="true" :handoff-search="handoffSearch" :parameters="{country_id:countryId,source_kind:'cycle'}" :audience="auth.hasPermission('sales_management.operating_orders.manage')?'operator':'viewer'" @select="openDraft" />
    <p v-else>请选择国家后查询补货参考。</p>
  </AppPage>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import OperatingReferenceV2 from '../../components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../../stores/auth';
import { requestApi } from '../../api/request';
import { stageCockpitDraft } from '../../utils/cockpitDraft';
const auth=useAuthStore(),router=useRouter(),route=useRoute(),countries=ref([]),countryId=ref(null),error=ref('');
const handoffCountry = computed(() => {
  const raw = route.query.country_id;
  return typeof raw === 'string' && /^[1-9][0-9]*$/.test(raw) && Number.isSafeInteger(Number(raw)) ? Number(raw) : null;
});
const handoffSearch = computed(() => {
  const raw = route.query.search;
  return countryId.value === handoffCountry.value && typeof raw === 'string' ? raw.trim().slice(0, 100) : '';
});
watch([countries, handoffCountry], ([options, requested]) => {
  if (requested && options.some(country => country.id === requested)) countryId.value = requested;
});
onMounted(async()=>{try{
  const result=await requestApi({method:'get',url:'/api/internal/commerce/inventory/country-decisions/',params:{limit:20,offset:0}});
  if(!result?.success)throw Error(result?.message || '国家选项读取失败');
  countries.value=result.data?.countries || [];
}catch(e){error.value=e.message || '国家选项读取失败';}});
function openDraft(selection){try{stageCockpitDraft(auth.currentUser,selection);router.push('/sales-management/operating-orders');}catch(e){error.value=e.message;}}
</script>
