<template>
  <span
    class="spu-code-display"
    :class="{ 'spu-code-display--structured': parts }"
    :aria-label="accessibleLabel"
  >
    <template v-if="parts">
      <span class="spu-code-display__category" :title="`类目编码：${parts.category}`">{{ parts.category }}</span><span
        class="spu-code-display__tail"
        :title="`属性/季节码及流水号：${parts.tail}`"
      >{{ parts.tail }}</span>
    </template>
    <template v-else>{{ displayCode }}</template>
  </span>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  code: { type: [String, Number], default: '' },
  placeholder: { type: String, default: '-' }
});

const displayCode = computed(() => {
  const value = String(props.code ?? '').trim();
  return value || props.placeholder;
});

/**
 * The formal SPU format is category code + one attribute/season digit + a
 * three-digit sequence. Only an all-numeric code with at least seven digits
 * can be identified safely; legacy and ad-hoc codes remain untouched.
 */
const parts = computed(() => {
  const value = String(props.code ?? '').trim();
  if (!/^\d{7,}$/.test(value)) return null;
  return { category: value.slice(0, -4), tail: value.slice(-4) };
});

const accessibleLabel = computed(() => {
  if (!parts.value) return `SPU编码：${displayCode.value}`;
  return `SPU编码：${displayCode.value}；类目编码：${parts.value.category}；属性/季节码及流水号：${parts.value.tail}`;
});
</script>

<style scoped>
.spu-code-display {
  display: inline-flex;
  align-items: baseline;
  max-width: 100%;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.spu-code-display__category {
  color: #0f766e;
  font-weight: 700;
  text-decoration: underline;
  text-decoration-color: #5eead4;
  text-decoration-thickness: 2px;
  text-underline-offset: 2px;
}

.spu-code-display__tail {
  color: inherit;
}
</style>
