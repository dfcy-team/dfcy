<template>
  <el-image class="product-image" :src="imageUrl" :preview-src-list="imageUrl ? [imageUrl] : []" fit="contain" preview-teleported alt="商品图片" :title="imageUrl ? '点击查看大图' : ''">
    <template #error><span class="image-empty">{{loading ? '图片加载中' : source ? '图片暂不可用' : '暂无商品图片'}}</span></template>
  </el-image>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue';
import {fetchApiFile} from '../../api/request';
const props=defineProps({orderId:{type:[Number,String],required:true},skuId:{type:[Number,String],required:true},source:{type:String,default:''}});
const imageUrl=ref(''),loading=ref(false);let sequence=0;
function release(){if(imageUrl.value)URL.revokeObjectURL(imageUrl.value);imageUrl.value='';}
watch(()=>[props.orderId,props.skuId,props.source],async()=>{
  const current=++sequence;release();if(!props.source){loading.value=false;return;}
  loading.value=true;
  try{
    const result=await fetchApiFile(`/api/external/supplier/supply-chain/v2/purchase-orders/${encodeURIComponent(props.orderId)}/skus/${encodeURIComponent(props.skuId)}/image/`);
    if(current===sequence&&result?.success)imageUrl.value=URL.createObjectURL(result.blob);
  } finally {if(current===sequence)loading.value=false;}
},{immediate:true});
onBeforeUnmount(()=>{sequence++;release();});
</script>
<style scoped>
.product-image{width:112px;height:112px;border:1px solid #e5e7eb;border-radius:8px;flex-shrink:0}.image-empty{display:flex;align-items:center;justify-content:center;height:100%;font-size:12px;color:#667085}@media(max-width:650px){.product-image{width:88px;height:88px}}
</style>
