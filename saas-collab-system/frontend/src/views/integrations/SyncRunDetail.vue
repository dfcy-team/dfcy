<template><SyncExecutionRecords :detail-id="route.params.id" /></template>
<script setup>
import { useRoute } from 'vue-router';
import SyncExecutionRecords from './SyncExecutionRecords.vue';
const route = useRoute();
</script>
