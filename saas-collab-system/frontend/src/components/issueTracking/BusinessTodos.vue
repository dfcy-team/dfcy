<template><section><header><h3>自动业务待办（{{total}}）</h3><el-button :loading="busy" @click="load">刷新</el-button></header><p>批次到仓达到设置的自然日天数且尚无确认入库记录时提醒；已有部分确认入库不再提醒。按北京时间计算，不计入消息未读。</p><el-alert v-if="error" :title="error" type="error"/><el-table :data="items" v-loading="busy" empty-text="暂无到仓超期未入库批次"><el-table-column prop="number" label="批次"/><el-table-column prop="country" label="国家"/><el-table-column prop="warehouse" label="计划目的仓"/><el-table-column label="到仓时间"><template #default="{row}">{{trackingTime(row.arrived_at)}}</template></el-table-column><el-table-column prop="arrived_days" label="已到仓天数"/><el-table-column prop="pending_quantity" label="待入库件数"/><el-table-column label="处理"><template #default="{row}"><router-link :to="row.path">查看批次</router-link></template></el-table-column></el-table><el-pagination v-model:current-page="page" :page-size="20" :total="total" @current-change="load" layout="total,prev,pager,next"/></section></template>
<script setup>
import {ref,onMounted,onBeforeUnmount} from 'vue';
import {tracking} from '../../api/issueTracking';
import {trackingTime} from './display';
const items=ref([]),total=ref(0),page=ref(1),busy=ref(false),error=ref('');let generation=0;
async function load(){const token=++generation;busy.value=true;error.value='';try{const data=await tracking('business-todos/','get',null,{page:page.value});if(token===generation){items.value=data.results||[];total.value=data.count||0;}}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)busy.value=false;}}
onMounted(()=>{load();window.addEventListener('focus',load);});onBeforeUnmount(()=>{generation++;window.removeEventListener('focus',load);});
</script>
