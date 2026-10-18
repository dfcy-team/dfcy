<template><span class="country-value" :title="label || normalized"><img v-if="filename && !failed" :src="source" width="18" height="13" loading="lazy" decoding="async" alt="" aria-hidden="true" @error="failed=true"/><span>{{label || normalized || '—'}}</span></span></template>
<script setup>
import {computed,ref,watch} from 'vue';
import manifest from '../../assets/countryFlagManifest.json';
const props=defineProps({code:{type:String,default:''},label:{type:String,default:''}});
const failed=ref(false);const normalized=computed(()=>String(props.code||'').trim().toUpperCase());
const filename=computed(()=>manifest[normalized.value]||'');
const source=computed(()=>`${import.meta.env.BASE_URL || '/'}assets/country-flags/${filename.value}`);
watch(normalized,()=>{failed.value=false;});
</script>
<style scoped>.country-value{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:inherit;line-height:inherit;max-width:100%}.country-value img{width:18px;height:13px;flex:none;object-fit:contain;border:1px solid #e4e8ef}.country-value>span{min-width:0;overflow:hidden;text-overflow:ellipsis}</style>
