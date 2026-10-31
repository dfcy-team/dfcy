<template>
  <section class="reminders">
    <el-button type="primary" plain @click="toggle">{{opened?'收起':'查看'}}付款到期提醒</el-button>
    <template v-if="opened">
      <p>按当前国家和账号权限查询未结清单据；缺少账期、起算事件或金额的单据需人工核对。本页查询不会发送消息；主动提醒可在飞书协同的通知规则中配置“供应链付款到期提醒”，按接收人权限每日去重推送。</p>
      <div class="filters">
        <el-select v-model="kind" aria-label="提醒费用类型" @change="reset"><el-option v-for="(label,value) in kinds" :key="value" :label="label" :value="value"/></el-select>
        <el-select v-model="status" aria-label="付款到期状态" @change="reset"><el-option label="已逾期" value="overdue"/><el-option label="即将到期（含当天）" value="due_soon"/><el-option label="待确认" value="unknown"/><el-option label="全部未结清" value="all"/></el-select>
        <el-button :loading="loading" @click="reset">刷新提醒</el-button>
      </div>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-table :data="rows" border v-loading="loading" empty-text="当前范围没有待处理提醒">
        <el-table-column label="单号" min-width="165"><template #default="{row}"><el-button link type="primary" @click="emit('open',row)">{{row.number}}</el-button></template></el-table-column>
        <el-table-column prop="country_name" label="国家" min-width="100"/>
        <el-table-column prop="party_name" label="供应商 / 货运公司" min-width="155"/>
        <el-table-column label="到期日" min-width="115"><template #default="{row}">{{row.due_date||'待确认'}}</template></el-table-column>
        <el-table-column label="剩余应付" min-width="120"><template #default="{row}">{{row.remaining_amount==null?'待核对':row.remaining_amount}}</template></el-table-column>
        <el-table-column label="状态" min-width="120"><template #default="{row}"><el-tag :type="row.status==='overdue'?'danger':row.status==='due_soon'?'warning':'info'">{{labels[row.status]||row.status}}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="145"><template #default="{row}"><el-button link type="primary" @click="emit('open',row)">账期 / 付款明细</el-button></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="20" :total="total" layout="total,prev,pager,next" @current-change="changePage"/>
    </template>
  </section>
</template>
<script setup>
import {ref,watch,onUnmounted} from 'vue';
import {fetchPaymentReminders} from '../../api/paymentTermsV2';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
const props=defineProps({countryId:[String,Number]});
const emit=defineEmits(['open']);
const auth=useAuthStore(),opened=ref(false),loading=ref(false),error=ref(''),rows=ref([]),total=ref(0),page=ref(1),kind=ref('shipment'),status=ref('overdue');
const kinds={shipment:'供应商货款',domestic_freight:'国内运费',batch:'批次货运费',inbound:'入库清关费'},labels={overdue:'已逾期',due_soon:'即将到期',unknown:'待确认',scheduled:'未到提醒期',settled:'已结清'};
let generation=0;
async function load(){const token=++generation;rows.value=[];total.value=0;loading.value=true;error.value='';try{const r=await fetchPaymentReminders({kind:kind.value,status:status.value,limit:20,offset:(page.value-1)*20,...(props.countryId?{country_id:props.countryId}:{})});if(token!==generation)return;if(!r?.success)throw new Error(r?.message||'到期提醒读取失败');rows.value=r.data||[];total.value=Number(r.count||0);}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function toggle(){opened.value=!opened.value;if(opened.value)return reset();generation++;loading.value=false;}
function reset(){page.value=1;return load();}
function changePage(value){page.value=value;return load();}
function refresh(){if(opened.value)return load();}
watch(()=>props.countryId,()=>{generation++;rows.value=[];if(opened.value)reset();});
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;opened.value=false;rows.value=[];total.value=0;loading.value=false;},{flush:'sync'});
onUnmounted(()=>generation++);
defineExpose({toggle,load,refresh,kind,status,rows,total});
</script>
<style scoped>
.reminders{padding:14px;border:1px solid #dce4ef;border-radius:8px;margin:14px 0;background:#fff}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.filters :deep(.el-select){width:210px}p{font-size:13px;color:#64748b}
</style>
