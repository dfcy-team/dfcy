<template>
  <section>
    <h2>运营订货确认通知</h2>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-form label-position="top">
      <el-form-item label="接收采购员"><el-select v-model="form.recipient_user_ids" multiple filterable :disabled="!canManage || busy"><el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id"/></el-select></el-form-item>
      <el-form-item label="确认后自动通知"><el-switch v-model="form.enabled" :disabled="!canManage || busy"/></el-form-item>
    </el-form>
    <p>运营订货单确认后，通过飞书私信提醒所选采购员对接供应商。接收人需绑定飞书，并具有对应订货单的采购查看权限。</p>
    <el-button v-if="canManage" type="primary" :loading="busy" @click="save">保存设置</el-button>
  </section>
</template>
<script setup>
import {onMounted,ref,reactive} from 'vue';
import {requestApi} from '../../api/request';
const url='/api/internal/supply-chain/v2/settings/operating-notification/';
const form=reactive({enabled:false,recipient_user_ids:[]});
const users=ref([]),canManage=ref(false),busy=ref(false),error=ref('');
function hydrate(data){Object.assign(form,{enabled:data.enabled,recipient_user_ids:data.recipient_user_ids});users.value=data.users;canManage.value=data.can_manage;}
async function load(){try{const response=await requestApi({method:'get',url});if(!response.success)throw Error(response.message);hydrate(response.data);}catch(e){error.value=e.message;}}
async function save(){if(busy.value)return;busy.value=true;error.value='';try{const response=await requestApi({method:'put',url,data:{...form}});if(!response.success)throw Error(response.message);hydrate(response.data);}catch(e){error.value=e.message;}finally{busy.value=false;}}
onMounted(load);
</script>
