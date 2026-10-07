<template><el-button v-if="canAccessPath(auth.currentUser, '/reports/basic')" @click="open">{{ module }}组合看板</el-button></template>
<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
const props = defineProps({ module: { type: String, required: true } });
const auth = useAuthStore(), router = useRouter();
function open() { router.push({ path: '/reports/basic', query: { tab: 'dashboard', module: props.module } }); }
</script>
