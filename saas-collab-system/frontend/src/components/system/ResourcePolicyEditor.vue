<template>
  <el-dialog v-model="open" :title="`资源范围 / ${adminRoleDisplayName(role)}`" width="min(760px, 96vw)" @open="load">
    <el-alert title="此处策略只覆盖所选资源；未列出的资源继续使用角色基础范围。仓库和供应商限制会原样保留。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-loading="loading">
      <section v-for="definition in definitions" :key="definition.resource_code" class="resource-policy">
        <el-checkbox v-model="enabled[definition.resource_code]">{{ definition.name || definition.resource_code }}</el-checkbox>
        <template v-if="enabled[definition.resource_code]">
          <el-select v-model="policyMap[definition.resource_code].scope_type" aria-label="范围类型" placeholder="请选择授权范围"><el-option label="全部" value="all"/><el-option label="自定义" value="custom"/></el-select>
          <div v-if="policyMap[definition.resource_code].scope_type === 'custom'" class="dimensions">
            <label v-for="dimension in definition.dimensions || []" :key="dimension">{{ dimensionLabel(dimension) }}
              <el-select v-model="policyMap[definition.resource_code].config[dimension]" multiple filterable :remote="isProductDimension(dimension)" :remote-method="query => searchProducts(dimension, query)" collapse-tags :loading="optionsLoading" :disabled="optionsLoading || Boolean(optionsError)" :placeholder="`选择${dimensionLabel(dimension)}`"><el-option v-for="item in optionItems(dimension)" :key="item.id" :label="optionLabel(dimension,item)" :value="item.id"/></el-select>
            </label>
          </div>
        </template>
      </section>
      <el-alert v-if="operationPolicies.length" title="以下操作级策略只读保留；保存资源通配策略时会一并保留，不会被删除。" type="info" :closable="false" />
      <el-table v-if="operationPolicies.length" :data="operationPolicies" size="small">
<el-table-column label="资源"><template #default="{row}">{{ resourceLabel(row.resource_code) }}</template></el-table-column><el-table-column label="具体操作"><template #default="{row}">{{ adminPermissionLabel(row.permission_code) }}<small class="policy-code">{{ row.permission_code }}</small></template></el-table-column><el-table-column label="操作范围"><template #default="{row}">{{ scopeSummary(row) }}</template></el-table-column>
      </el-table>
      <el-alert v-if="optionsError" :title="optionsError" type="error" :closable="false"/><el-button v-if="optionsError" size="small" @click="loadOptions">重新加载范围选项</el-button>
    </div>
    <template #footer><el-button @click="open=false">取消</el-button><el-button type="primary" :disabled="!saveReady || policiesVersion === null || policiesVersion === undefined || optionsLoading || Boolean(optionsError) || auth.authorizationStale" :loading="saving" @click="save">保存策略</el-button></template>
  </el-dialog>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { adminPermissionLabel, adminRoleDisplayName } from '../../utils/adminDisplayLabels';
import { useAuthStore } from '../../stores/auth';
import { formatApiError } from '../../api/request';
import { buildResourcePoliciesForSave, splitResourcePolicies } from '../../utils/authorizationPreview';
import { fetchRoleScopeOptions } from '../../api/systemAdmin';
import { fetchResourcePolicies, saveResourcePolicies } from '../../api/authorization';
const props=defineProps({modelValue:Boolean,role:Object});const emit=defineEmits(['update:modelValue','saved']);
const auth=useAuthStore();
const open=ref(false),loading=ref(false),saving=ref(false),error=ref(''),optionsError=ref(''),optionsLoading=ref(false),policiesVersion=ref(null);
watch(()=>props.modelValue,v=>open.value=v);watch(open,v=>emit('update:modelValue',v));
const definitions=ref([]), enabled=reactive({}), policyMap=reactive({}), options=ref({});
const operationPolicies=ref([]);
const dimensionsMap={platform_ids:'platforms',site_ids:'sites',store_ids:'stores',warehouse_ids:'warehouses',supplier_ids:'suppliers',sku_ids:'skus',spu_ids:'spus'};
const dimensionLabel=d=>({platform_ids:'平台',site_ids:'站点/国家',store_ids:'店铺',warehouse_ids:'仓库',supplier_ids:'供应商',sku_ids:'商品SKU',spu_ids:'产品SPU'}[d]||d);
const optionItems=d=>options.value[dimensionsMap[d]]||[];
const optionLabel=(d,item)=>isProductDimension(d)?`${item.code||item.id} · ${item.name||item.code||item.id}`:(item.name||item.label||item.code||item.id);
const isProductDimension=d=>d==='sku_ids'||d==='spu_ids';
async function loadOptions(params={}){optionsLoading.value=true;optionsError.value='';const r=await fetchRoleScopeOptions(params);optionsLoading.value=false;if(!r?.success){optionsError.value=r?.message||'范围选项加载失败';return;}options.value={...options.value,...(r.data||{})};if(params.include_products)options.value={...options.value,skus:r.data?.skus||[],spus:r.data?.spus||[]};}
async function searchProducts(dimension,query){const selected=ids=>Object.values(policyMap).flatMap(p=>p.config?.[ids]||[]);await loadOptions({include_products:true,product_search:(query||'').trim(),selected_sku_ids:selected('sku_ids').join(','),selected_spu_ids:selected('spu_ids').join(',')});}
async function load(){if(!props.role?.id)return;loading.value=true;error.value='';await loadOptions();const r=await fetchResourcePolicies(props.role.id);loading.value=false;if(!r?.success){error.value=r?.message||'资源策略加载失败';return;}definitions.value=r.data?.definitions||[];policiesVersion.value=r.data?.template_version;Object.keys(enabled).forEach(k=>delete enabled[k]);Object.keys(policyMap).forEach(k=>delete policyMap[k]);const {wildcardByResource,operationPolicies:exactPolicies}=splitResourcePolicies(definitions.value,r.data?.policies||[]);operationPolicies.value=exactPolicies;for(const d of definitions.value){const p=wildcardByResource[d.resource_code];enabled[d.resource_code]=Boolean(p);policyMap[d.resource_code]=p?{...p,config:{...(p.config||{})}}:{resource_code:d.resource_code,permission_code:'*',scope_type:'',config:{}};}await loadOptions({include_products:true,selected_sku_ids:Object.values(policyMap).flatMap(p=>p.config?.sku_ids||[]).join(','),selected_spu_ids:Object.values(policyMap).flatMap(p=>p.config?.spu_ids||[]).join(',')});}
function resourceLabel(code){return definitions.value.find(definition=>definition.resource_code===code)?.name || '其他资源';}
const policies=computed(()=>buildResourcePoliciesForSave(definitions.value,enabled,policyMap,operationPolicies.value));
const saveReady=computed(()=>definitions.value.filter(d=>enabled[d.resource_code]).every(d=>{
  const policy=policyMap[d.resource_code];
  if(policy.scope_type==='all')return true;
  if(policy.scope_type!=='custom')return false;
  return Object.values(policy.config||{}).some(values=>Array.isArray(values)&&values.length>0);
}));
const dimensionLabels={platform_ids:'平台',site_ids:'站点/国家',store_ids:'店铺',warehouse_ids:'仓库',supplier_ids:'供应商',sku_ids:'商品SKU',spu_ids:'产品SPU'};
function scopeSummary(row){if(row.scope_type==='all')return '资源全部范围';return Object.entries(row.config||{}).map(([key,values])=>`${dimensionLabels[key]||key}：${Array.isArray(values)?values.join('、'):values}`).join('；')||'自定义范围';}
async function save(){if(auth.authorizationStale||!auth.hasPermission('system.roles.manage')){error.value='当前授权状态无效或缺少角色管理权限，无法保存。';return;}saving.value=true;const r=await saveResourcePolicies(props.role.id,{expected_version:policiesVersion.value,policies:policies.value});saving.value=false;if(!r?.success){error.value=r?.http_status===409?'策略版本冲突，请关闭后重新打开并加载最新策略。':formatApiError(r)||r?.message||'资源策略保存失败';return;}ElMessage.success('资源策略已保存');emit('saved');open.value=false;}
</script>
<style scoped>.resource-policy{padding:12px 0;border-bottom:1px solid #e5e7eb;display:grid;gap:10px}.dimensions{display:grid;gap:10px}.dimensions label{display:grid;gap:5px;color:#475569}.resource-policy{padding:20px;margin:16px 0;border:1px solid #e4eaf3;border-radius:6px;background:#f8faff}.dimensions{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.resource-policy>.el-select{max-width:280px}.policy-code{display:block;color:#8a99af;font-size:11px;overflow-wrap:anywhere}@media(max-width:640px){.dimensions{grid-template-columns:1fr}}
</style>
