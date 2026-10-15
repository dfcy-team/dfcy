<template><SupplyProcurementV2 :archive-kind="kind" /></template>
<script setup>
import SupplyProcurementV2 from '../purchasing/SupplyProcurementV2.vue';
defineProps({kind:{type:String,required:true}});
</script>
