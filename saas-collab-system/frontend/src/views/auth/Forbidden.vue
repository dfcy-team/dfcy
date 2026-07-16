<template>
  <main class="standalone-state">
    <AppState status="forbidden" action-label="返回工作台" @action="router.push('/')" />
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router';
import AppState from '../../components/AppState.vue';

const router = useRouter();
</script>

<style scoped>
.standalone-state {
  width: min(720px, calc(100vw - 32px));
  margin: 80px auto;
}
</style>
