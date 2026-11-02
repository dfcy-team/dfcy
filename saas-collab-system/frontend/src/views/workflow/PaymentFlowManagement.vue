<template>
  <section class="flow-page" v-loading="loading">
    <header><h1>付款流程管理</h1><p>首批为单节点指定审批人。付款申请按部门、业务类型、公私性质和金额范围唯一匹配。合并付款同时匹配“合并付款审批”和每条来源付款类型规则，且必须指定同一审批人。部门留空表示全部部门；已发布版本不可修改，调整请创建新版本。</p></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="error" />
    <el-card shadow="never">
      <template #header>{{ sourceVersion ? `基于 ${sourceVersion.flow_key} v${sourceVersion.version} 创建下一版本` : '创建流程版本' }}</template>
      <el-form :model="form" label-position="top" class="form" @submit.prevent="create">
        <el-form-item label="流程编号" required><el-input v-model.trim="form.flow_key" /></el-form-item>
        <el-form-item label="付款类型" required><el-select v-model="form.payment_kind"><el-option v-for="x in kinds" :key="x.value" :label="x.label" :value="x.value" /></el-select></el-form-item>
        <el-form-item label="公私性质" required><el-select v-model="form.nature"><el-option label="对公" value="corporate" /><el-option label="对私" value="personal" /></el-select></el-form-item>
        <el-form-item label="部门"><el-select v-model="form.department_key" clearable placeholder="全部部门"><el-option v-for="d in departments" :key="d.id" :label="d.name" :value="String(d.id)" /></el-select></el-form-item>
        <el-form-item label="最低金额" required><el-input v-model="form.minimum_amount" type="number" min="0" step="0.0001" /></el-form-item>
        <el-form-item label="最高金额"><el-input v-model="form.maximum_amount" type="number" min="0" step="0.0001" placeholder="不限" /></el-form-item>
        <el-form-item label="指定审批人" required><el-select v-model="form.reviewer_id" placeholder="选择有审批及入账权限的人员"><el-option v-for="u in reviewers" :key="u.id" :label="u.name" :value="String(u.id)" /></el-select></el-form-item>
        <el-form-item><el-button type="primary" :loading="saving" @click="create">{{ sourceVersion ? '创建下一版本草稿' : '保存草稿版本' }}</el-button><el-button v-if="sourceVersion" @click="clearVersion">取消版本编辑</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card shadow="never" class="list-card">
      <template #header>流程版本</template>
      <el-table v-if="rows.length" :data="rows" row-key="id">
        <el-table-column label="流程/版本" min-width="170"><template #default="{row}">{{ row.flow_key }} / v{{ row.version }}</template></el-table-column>
        <el-table-column label="匹配条件" min-width="280"><template #default="{row}">{{ kindLabel(row.payment_kind) }} · {{ row.nature === 'personal' ? '对私' : '对公' }} · {{ departmentLabel(row.department_key) }} · {{ row.minimum_amount }}–{{ row.maximum_amount ?? '不限' }}</template></el-table-column>
        <el-table-column prop="reviewer_name" label="审批人" min-width="120" />
        <el-table-column label="状态" width="100"><template #default="{row}">{{ row.published ? (row.active ? '已发布' : '已停用') : '草稿' }}</template></el-table-column>
        <el-table-column label="操作" width="220"><template #default="{row}"><el-button v-if="!row.published" link type="primary" :loading="saving" @click="act(row,'publish')">发布</el-button><el-button v-else-if="row.active" link type="danger" :loading="saving" @click="act(row,'disable')">停用</el-button><el-button v-if="row.published" link type="primary" @click="startNextVersion(row)">创建新版本</el-button></template></el-table-column>
      </el-table>
      <el-empty v-else description="暂无付款流程版本" />
    </el-card>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createPaymentFlow, fetchPaymentFlowDepartments, fetchPaymentFlowReviewers, fetchPaymentFlows, updatePaymentFlowStatus } from '../../api/workflow';
const kinds = [
  { value: 'purchase', label: '采购定金' },
  { value: 'shipment', label: '供应商货款' },
  { value: 'domestic_freight', label: '国内运费' },
  { value: 'batch', label: '国际/批次货运费' },
  { value: 'inbound', label: '入库费用' },
  { value: 'payment_batch', label: '合并付款审批' }
];
const kindLabel = (v) => kinds.find(x => x.value === v)?.label || v;
const rows = ref([]), reviewers = ref([]), departments = ref([]), error = ref(''), loading = ref(false), saving = ref(false), sourceVersion = ref(null);
const departmentNames = computed(() => new Map(departments.value.map(d => [String(d.id), d.name])));
const departmentLabel = (key) => key ? (departmentNames.value.get(String(key)) || '未知部门') : '全部部门';
const form = reactive({flow_key:'',payment_kind:'purchase',nature:'corporate',department_key:'',minimum_amount:'0',maximum_amount:'',reviewer_id:''});
function startNextVersion(row){Object.assign(form,{flow_key:row.flow_key,payment_kind:row.payment_kind,nature:row.nature,department_key:String(row.department_key || ''),minimum_amount:String(row.minimum_amount),maximum_amount:row.maximum_amount == null ? '' : String(row.maximum_amount),reviewer_id:String(row.reviewer_id)});sourceVersion.value=row;error.value='';}
function clearVersion(){sourceVersion.value=null;Object.assign(form,{flow_key:'',payment_kind:'purchase',nature:'corporate',department_key:'',minimum_amount:'0',maximum_amount:'',reviewer_id:''});}
function requireSuccess(response){if(response?.success !== true){throw new Error(response?.message || '操作失败，请稍后重试。');}return response;}
const unwrap = (response) => response?.data?.data ?? response?.data ?? [];
async function load(){ loading.value=true; error.value=''; try { const [r,u,d]=await Promise.all([fetchPaymentFlows(),fetchPaymentFlowReviewers(),fetchPaymentFlowDepartments()]); rows.value=unwrap(requireSuccess(r)); reviewers.value=unwrap(requireSuccess(u)); departments.value=unwrap(requireSuccess(d)); } catch(e){error.value=e?.response?.data?.message || e?.message || '流程配置加载失败。';} finally {loading.value=false;} }
async function create(){ if(!form.flow_key || !form.reviewer_id) return; error.value=''; saving.value=true; try { requireSuccess(await createPaymentFlow({...form, maximum_amount:form.maximum_amount === '' ? null : form.maximum_amount, reviewer_id:Number(form.reviewer_id)})); clearVersion(); await load(); } catch(e){error.value=e?.response?.data?.message || e?.message || '保存失败，请检查配置。';} finally {saving.value=false;} }
async function act(row,action){error.value=''; saving.value=true; try{requireSuccess(await updatePaymentFlowStatus(row.id,action)); await load();}catch(e){error.value=e?.response?.data?.message || e?.message || '操作失败。';}finally{saving.value=false;}}
onMounted(load);
</script>
<style scoped>
.flow-page{padding:24px}.flow-page header{margin-bottom:20px}.flow-page p{color:var(--el-text-color-secondary)}.error{margin-bottom:16px}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.form :deep(.el-select){width:100%}.list-card{margin-top:18px}
</style>
