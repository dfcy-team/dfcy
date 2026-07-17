<template>
  <section class="pending-page">
    <header class="page-header"><div><p class="eyebrow">UI-P5 · 受控待接入</p><h1 class="page-title">{{ title }}</h1><p>{{ contract }}</p></div><el-tag type="info">{{ state }}</el-tag></header>
    <el-alert title="后端合同尚未实现：API 模式不会发送不存在的请求，高风险操作保持禁用。" type="warning" show-icon :closable="false"/>
    <el-table v-loading="loading" :data="rows" border empty-text="暂无 Mock 数据"><el-table-column v-for="field in fields" :key="field.prop" :prop="field.prop" :label="field.label" :min-width="field.width||120"/></el-table>
    <div class="actions"><el-button v-for="action in actions" :key="action" disabled>{{action}}</el-button></div>
  </section>
</template>
<script setup>
import{onMounted,ref}from'vue';import{collectionRows,apiState}from'../utils/businessResponse';
const props=defineProps({title:{type:String,required:true},contract:{type:String,required:true},fields:{type:Array,default:()=>[]},actions:{type:Array,default:()=>[]},loader:{type:Function,required:true}});const rows=ref([]),loading=ref(false),state=ref('pending');onMounted(async()=>{loading.value=true;const response=await props.loader();if(response.success){rows.value=collectionRows(response.data);state.value=apiState(response.data,'pending')}else state.value='error';loading.value=false});
</script>
<style scoped>.pending-page{display:grid;gap:16px}.page-header{display:flex;justify-content:space-between;gap:16px}.page-header p{margin:4px 0 0;color:#64748b}.eyebrow{font-size:12px;font-weight:700;color:#0f766e!important}.actions{display:flex;gap:8px;flex-wrap:wrap}</style>
