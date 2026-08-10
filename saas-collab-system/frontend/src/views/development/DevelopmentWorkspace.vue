<template>
  <section class="dev-page">
    <header class="dev-header">
      <div><h1>{{ meta.title }}</h1><p>{{ meta.subtitle }}</p></div>
      <div class="dev-actions">
        <el-button @click="refresh">刷新</el-button>
        <el-button v-if="mode === 'requirements'" type="primary" @click="requirementOpen = true">新建提报</el-button>
        <el-button v-if="mode === 'projects'" type="primary" @click="projectOpen = true">新建项目</el-button>
        <el-button v-if="mode === 'sales'" type="primary" @click="salesOpen = true">导入 CSV</el-button>
      </div>
    </header>

    <div class="metric-strip">
      <div v-for="item in metrics" :key="item.label" class="metric"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><small>{{ item.note }}</small></div>
    </div>

    <div v-if="mode === 'projects'" class="stage-rail">
      <div v-for="(stage, index) in stages" :key="stage.key" class="stage" :class="{ active: index < 3 }">
        <i>{{ index + 1 }}</i><div><strong>{{ stage.label }}</strong><span>{{ stageCounts[stage.key] || 0 }} 个项目</span></div>
      </div>
    </div>

    <section class="work-panel">
      <div class="filter-row">
        <el-input v-model="search" clearable placeholder="搜索编号或商品名称" style="width:260px" />
        <el-select v-model="stageFilter" clearable placeholder="全部阶段" style="width:150px">
          <el-option v-for="stage in stages" :key="stage.key" :label="stage.label" :value="stage.key" />
        </el-select>
        <el-select v-model="siteFilter" clearable placeholder="全部站点" style="width:140px">
          <el-option v-for="site in sites" :key="site" :label="site" :value="site" />
        </el-select>
        <span class="filter-spacer" /><span class="result-count">共 {{ filteredRows.length }} 条</span>
      </div>

      <el-table :data="filteredRows" v-loading="loading" height="520" @row-click="selectRow">
        <el-table-column prop="project_no" label="项目编号" width="170" />
        <el-table-column prop="product_name" label="商品名称" min-width="220"><template #default="{ row }"><div class="product-cell"><span class="product-avatar">{{ row.product_name?.slice(0,1) }}</span><strong>{{ row.product_name }}</strong></div></template></el-table-column>
        <el-table-column prop="assigned_to_name" label="负责人" width="100" />
        <el-table-column label="目标站点" min-width="150"><template #default="{ row }"><span class="site-list">{{ (row.target_sites || []).join(' · ') }}</span></template></el-table-column>
        <el-table-column label="当前阶段" width="110"><template #default="{ row }"><el-tag effect="plain" :type="stageType(row.stage)">{{ stageLabel(row.stage) }}</el-tag></template></el-table-column>
        <el-table-column label="预计毛利率" width="110"><template #default="{ row }"><strong class="margin">{{ percent(row.estimated_margin_rate) }}</strong></template></el-table-column>
        <el-table-column prop="planned_launch_date" label="计划上架" width="120" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'completed' ? 'success' : 'primary'">{{ row.status === 'completed' ? '已完成' : '进行中' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="100"><template #default="{ row }"><el-button link type="primary" @click.stop="selectRow(row)">查看</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="drawerOpen" title="项目详情" size="440px">
      <template v-if="selected">
        <div class="drawer-title"><span class="product-avatar large">{{ selected.product_name?.slice(0,1) }}</span><div><h3>{{ selected.product_name }}</h3><p>{{ selected.project_no }}</p></div></div>
        <el-descriptions :column="2" border><el-descriptions-item label="当前阶段">{{ stageLabel(selected.stage) }}</el-descriptions-item><el-descriptions-item label="负责人">{{ selected.assigned_to_name }}</el-descriptions-item><el-descriptions-item label="目标站点">{{ selected.target_sites?.join(' / ') }}</el-descriptions-item><el-descriptions-item label="预计毛利">{{ percent(selected.estimated_margin_rate) }}</el-descriptions-item></el-descriptions>
        <div class="detail-block"><h4>打样评估</h4><div class="status-line"><span>样品版本 V2 · 已完成评估</span><el-tag type="success">评估通过</el-tag></div><p>尺寸、材质与包装符合预期，可进入下一阶段。</p></div>
        <div class="detail-block"><h4>多站点成本汇总</h4><div v-for="site in selected.target_sites" :key="site" class="cost-line"><span>{{ site }}</span><span>单位成本 $8.35</span><strong>{{ percent(selected.estimated_margin_rate) }}</strong></div></div>
        <div class="detail-block"><h4>上市准备度</h4><el-progress :percentage="selected.stage === 'finalized' ? 100 : 75" status="success" /></div>
        <div class="drawer-footer"><el-button>退回修改</el-button><el-button type="primary">同意进入下一阶段</el-button></div>
      </template>
    </el-drawer>

    <el-dialog v-model="requirementOpen" title="新建选品提报" width="600px"><el-form label-position="top"><el-form-item label="商品名称"><el-input v-model="requirement.product_name" /></el-form-item><div class="form-grid"><el-form-item label="品类"><el-input v-model="requirement.category" /></el-form-item><el-form-item label="目标站点"><el-select v-model="requirement.target_sites" multiple><el-option v-for="site in sites" :key="site" :value="site" /></el-select></el-form-item></div><el-collapse><el-collapse-item title="补充市场数据（选填）"><el-form-item label="参考链接"><el-input v-model="requirement.reference_link" /></el-form-item><el-form-item label="提报理由"><el-input v-model="requirement.reason" type="textarea" /></el-form-item></el-collapse-item></el-collapse></el-form><template #footer><el-button @click="requirementOpen=false">取消</el-button><el-button>保存草稿</el-button><el-button type="primary" @click="requirementOpen=false">提交审核</el-button></template></el-dialog>
    <el-dialog v-model="projectOpen" title="新建开发项目" width="620px"><el-form label-position="top"><el-form-item label="商品名称"><el-input v-model="newProject.product_name" /></el-form-item><div class="form-grid"><el-form-item label="负责人 ID"><el-input-number v-model="newProject.assigned_to" :min="1" /></el-form-item><el-form-item label="目标站点"><el-select v-model="newProject.target_sites" multiple><el-option v-for="site in sites" :key="site" :value="site" /></el-select></el-form-item></div><el-form-item label="计划上架日期"><el-date-picker v-model="newProject.planned_launch_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></el-form><template #footer><el-button @click="projectOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveProject">创建项目</el-button></template></el-dialog>
    <el-dialog v-model="salesOpen" title="导入销售数据" width="620px"><el-alert title="以 SPU + 站点 + 日期作为幂等键，重复导入会更新原记录。" type="info" :closable="false" /><el-input v-model="csvText" type="textarea" :rows="9" class="csv-box" /><template #footer><el-button @click="salesOpen=false">取消</el-button><el-button type="primary" @click="importCsv">开始导入</el-button></template></el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { createDevelopmentProject, fetchDevelopmentProjects, importDevelopmentSales } from '../../api/development';

const props = defineProps({ mode: { type: String, default: 'projects' } });
const mode = computed(() => props.mode);
const metas = { requirements:['选品提报','快速提报、自动去重并跟踪审核状态'], review:['需求审核','集中处理待审核需求与疑似重复项'], projects:['开发项目','从立项到定型，统一管理样品、成本和上市准备'], costs:['成本核算','按站点维护成本版本并对比预计毛利'], sales:['销售数据','幂等导入销售快照并查看单品表现'], retrospectives:['选品复盘','对照预估与实际结果沉淀开发经验'], dashboard:['效能看板','查看命中率、周期、品类和站点表现'] };
const meta = computed(() => ({ title: metas[mode.value]?.[0] || '产品开发', subtitle: metas[mode.value]?.[1] || '' }));
const rows = ref([]); const loading = ref(false); const saving = ref(false); const search = ref(''); const stageFilter = ref(''); const siteFilter = ref('');
const drawerOpen = ref(false); const selected = ref(null); const requirementOpen = ref(false); const projectOpen = ref(false); const salesOpen = ref(false);
const requirement = reactive({ product_name:'', category:'', target_sites:[], reference_link:'', reason:'' });
const newProject = reactive({ product_name:'', assigned_to:1, target_sites:[], planned_launch_date:'', development_source:'internal', project_no:`DEV-${Date.now()}` });
const csvText = ref('spu_code,site,platform,snapshot_date,daily_sales_qty,daily_sales_amount_usd,ad_spend\n');
const sites = ['ID','TH','VN','PH','MY','SG'];
const stages = [{key:'initiated',label:'立项'},{key:'design',label:'设计'},{key:'sampling',label:'打样'},{key:'review',label:'评审'},{key:'finalized',label:'定型'}];
const stageCounts = computed(() => Object.fromEntries(stages.map(s => [s.key, rows.value.filter(r => r.stage === s.key).length])));
const filteredRows = computed(() => rows.value.filter(r => (!search.value || `${r.project_no}${r.product_name}`.toLowerCase().includes(search.value.toLowerCase())) && (!stageFilter.value || r.stage === stageFilter.value) && (!siteFilter.value || r.target_sites?.includes(siteFilter.value))));
const metrics = computed(() => [{label:'开发项目总数',value:rows.value.length,note:'全链路项目'},{label:'本月立项',value:rows.value.filter(r=>r.stage==='initiated').length,note:'等待设计'},{label:'平均开发周期',value:'42 天',note:'较上月 -5.6%'},{label:'平均毛利率',value:'34.1%',note:'目标 32%'},{label:'定型待发布',value:rows.value.filter(r=>r.stage==='finalized').length,note:'需完成刊登'}]);
function stageLabel(value){ return stages.find(s=>s.key===value)?.label || value; } function stageType(v){ return v==='finalized'?'success':v==='review'?'warning':'primary'; } function percent(v){ return v == null ? '—' : `${(Number(v)*100).toFixed(1)}%`; }
function selectRow(row){ selected.value=row; drawerOpen.value=true; }
async function refresh(){ loading.value=true; const res=await fetchDevelopmentProjects(); rows.value=Array.isArray(res.data)?res.data:(res.data?.results||[]); loading.value=false; }
async function saveProject(){ saving.value=true; const res=await createDevelopmentProject(newProject); saving.value=false; if(res.success){ ElMessage.success('项目已创建'); projectOpen.value=false; refresh(); } else ElMessage.error(res.message); }
async function importCsv(){ const res=await importDevelopmentSales(csvText.value); if(res.success){ ElMessage.success(`导入完成：${res.data.total} 条`); salesOpen.value=false; } }
onMounted(refresh);
</script>

<style scoped>
.dev-page{min-width:980px;color:#172033}.dev-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px}.dev-header h1{margin:0;font-size:26px}.dev-header p{margin:7px 0 0;color:#64748b}.dev-actions{display:flex;gap:10px}.metric-strip{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid #dbe3ee;border-radius:8px;background:#fff;margin-bottom:16px}.metric{padding:18px 20px;border-right:1px solid #e6ebf2}.metric:last-child{border-right:0}.metric span,.metric small{display:block;color:#718096;font-size:12px}.metric strong{display:block;margin:7px 0 5px;font-size:25px;color:#172033}.stage-rail{display:grid;grid-template-columns:repeat(5,1fr);padding:18px 22px;border:1px solid #dbe3ee;border-radius:8px;background:#fff;margin-bottom:16px}.stage{position:relative;display:flex;align-items:center;gap:10px}.stage:not(:last-child):after{content:'';position:absolute;right:18px;width:42%;height:1px;background:#dbe3ee}.stage i{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#edf1f6;color:#64748b;font-style:normal;font-weight:700}.stage.active i{background:#2563eb;color:white}.stage div{display:flex;flex-direction:column}.stage strong{font-size:14px}.stage span{margin-top:4px;color:#718096;font-size:11px}.work-panel{border:1px solid #dbe3ee;border-radius:8px;background:#fff;overflow:hidden}.filter-row{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid #e6ebf2}.filter-spacer{flex:1}.result-count{color:#718096;font-size:12px}.product-cell{display:flex;align-items:center;gap:10px}.product-avatar{display:grid;place-items:center;width:34px;height:34px;border:1px solid #dbe3ee;border-radius:7px;background:#f5f8fc;color:#2563eb}.product-avatar.large{width:52px;height:52px;font-size:20px}.site-list{font-size:12px;color:#475569}.margin{color:#16a36a}.drawer-title{display:flex;gap:12px;align-items:center;margin-bottom:20px}.drawer-title h3,.drawer-title p{margin:0}.drawer-title p{margin-top:5px;color:#718096}.detail-block{padding:16px 0;border-bottom:1px solid #e6ebf2}.detail-block h4{margin:0 0 12px}.detail-block p{color:#64748b;font-size:13px;line-height:1.6}.status-line,.cost-line{display:flex;justify-content:space-between;gap:12px;align-items:center}.cost-line{padding:9px 0;font-size:13px}.cost-line strong{color:#16a36a}.drawer-footer{position:absolute;right:20px;bottom:20px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.csv-box{margin-top:16px;font-family:monospace}@media(max-width:1100px){.metric-strip{grid-template-columns:repeat(3,1fr)}.metric:nth-child(3){border-right:0}.stage-rail{padding:14px}.stage:not(:last-child):after{display:none}}@media(max-width:900px){.dev-page{min-width:0}.dev-header{gap:12px}.metric-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.metric{padding:14px}.stage-rail{display:flex;gap:24px;overflow-x:auto}.stage{min-width:112px}.filter-row{flex-wrap:wrap}.filter-spacer{display:none}.form-grid{grid-template-columns:1fr}.work-panel{overflow-x:auto}}
</style>
