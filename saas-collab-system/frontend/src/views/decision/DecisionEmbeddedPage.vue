<template>
  <section class="decision-embed" :aria-busy="loading">
    <div v-if="loading" class="decision-embed__loading">正在加载经营决策内容…</div>
    <iframe
      ref="frame"
      :key="frameSource"
      class="decision-embed__frame"
      :class="{ 'is-ready': !loading }"
      :src="frameSource"
      :style="{ height: `${frameHeight}px` }"
      :title="`${currentLabel} · 经营决策`"
      @load="handleLoad"
    />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { findMenuLabel, menuItems } from '../../router/menu';

const route = useRoute();
const loading = ref(true);
const frame = ref();
const frameHeight = ref(Math.max(window.innerHeight - 104, 720));
let resizeObserver;
const currentLabel = computed(() => findMenuLabel(route.path, menuItems) || '经营决策');
const frameSource = computed(() => `/decision-app${route.path.slice('/decision'.length)}?embed=1`);

function syncFrameHeight() {
  const documentElement = frame.value?.contentDocument?.documentElement;
  if (!documentElement) return;
  frameHeight.value = Math.max(documentElement.scrollHeight, window.innerHeight - 104, 720);
}

async function handleLoad() {
  loading.value = false;
  await nextTick();
  syncFrameHeight();
  resizeObserver?.disconnect();
  const documentElement = frame.value?.contentDocument?.documentElement;
  if (documentElement) {
    resizeObserver = new ResizeObserver(syncFrameHeight);
    resizeObserver.observe(documentElement);
  }
}

watch(frameSource, () => {
  loading.value = true;
  resizeObserver?.disconnect();
});
onBeforeUnmount(() => resizeObserver?.disconnect());
</script>

<style scoped>
.decision-embed {
  position: relative;
  min-height: calc(100vh - 104px);
}

.decision-embed__loading {
  position: absolute;
  z-index: 1;
  inset: 0;
  display: grid;
  place-items: center;
  color: #64748b;
  font-size: 13px;
  background: #f4f6f8;
}

.decision-embed__frame {
  display: block;
  width: 100%;
  border: 0;
  background: #f4f6f8;
  opacity: 0;
}

.decision-embed__frame.is-ready { opacity: 1; }
</style>
