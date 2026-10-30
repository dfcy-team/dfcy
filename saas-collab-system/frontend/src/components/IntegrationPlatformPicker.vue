<script setup lang="ts">
import { computed } from 'vue';
import jifengLogo from '../assets/jifeng-wms-logo.png';
const props = withDefaults(defineProps<{
  modelValue: string | string[];
  options: string[];
  multiple?: boolean;
}>(), { multiple: false });
const emit = defineEmits<{
  'update:modelValue': [value: string | string[]];
  change: [value: string | string[]];
}>();
const selected = computed(() => Array.isArray(props.modelValue) ? props.modelValue : props.modelValue ? [props.modelValue] : []);
const choices = computed(() => [...new Set([...props.options, ...selected.value])].filter(Boolean));
function brand(value: string) {
  const key = value.toLowerCase().replace(/[ _-]/g, '');
  return ({ shopee: 'shopee', lazada: 'lazada', tiktok: 'tiktok', tiktokshop: 'tiktok', jifengwms: 'jifeng' } as Record<string, string>)[key] || '';
}
function select(value: string) {
  const next = props.multiple
    ? value ? selected.value.includes(value) ? selected.value.filter(item => item !== value) : [...selected.value, value] : []
    : value;
  emit('update:modelValue', next);
  emit('change', next);
}
</script>

<template>
  <div class="platform-picker" role="group" aria-label="平台筛选">
    <button type="button" :aria-pressed="selected.length === 0" @click="select('')">全部平台</button>
    <button v-for="value in choices" :key="value" type="button" :title="brand(value) === 'jifeng' ? '极风 WMS' : value" :aria-label="value" :aria-pressed="selected.includes(value)" @click="select(value)">
      <span v-if="brand(value)" class="logo-frame" aria-hidden="true"><img v-if="brand(value) === 'jifeng'" :src="jifengLogo" class="jifeng-logo" alt="" /><span v-else :class="['platform-logo', brand(value)]" /></span>
      <span v-else>{{ value }}</span>
    </button>
  </div>
</template>

<style scoped>
.platform-picker { display:flex; flex-wrap:wrap; gap:8px; width:100%; }
button { min-height:44px; min-width:106px; padding:6px 12px; border:1px solid #dce2ea; border-radius:6px; color:#334155; background:#fff; cursor:pointer; }
button[aria-pressed="true"] { border-color:#2563eb; box-shadow:inset 0 0 0 1px #2563eb; background:#eff6ff; }
button:focus-visible { outline:3px solid #93c5fd; outline-offset:2px; }
.logo-frame { display:block; position:relative; width:106px; height:30px; }
.jifeng-logo { display:block; width:106px; height:30px; object-fit:contain; }
.platform-logo { position:absolute; left:50%; top:50%; background-image:url('../assets/integration-platforms.png'); background-repeat:no-repeat; transform:translate(-50%,-50%) scale(var(--scale)); }
.shopee { width:140px; height:45px; background-position:-85px -112px; --scale:.65; }
.lazada { width:132px; height:35px; background-position:-89px -208px; --scale:.75; }
.tiktok { width:171px; height:32px; background-position:-68px -1019px; --scale:.6; }
</style>
