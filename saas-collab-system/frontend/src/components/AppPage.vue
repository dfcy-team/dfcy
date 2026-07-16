<template>
  <section class="app-page">
    <header class="app-page__header">
      <div class="app-page__heading">
        <div class="app-page__eyebrow">{{ eyebrow }}</div>
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <div class="app-page__actions">
        <el-tag :type="capabilityType" effect="plain">{{ capabilityLabel }}</el-tag>
        <slot name="action" />
      </div>
    </header>

    <el-alert
      v-if="boundaryNote"
      class="app-page__boundary"
      :title="boundaryNote"
      type="warning"
      :closable="false"
      show-icon
    />

    <div class="app-page__body">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  eyebrow: { type: String, default: 'WORKSPACE' },
  boundaryNote: { type: String, default: '' },
  capability: { type: String, default: 'connected' }
});

const capabilityLabels = {
  mock: 'Mock', pending: '待接入', sandbox: '沙箱', connected: '已连接', degraded: '降级', disabled: '已禁用'
};
const capabilityTypes = {
  mock: 'warning', pending: 'info', sandbox: 'warning', connected: 'success', degraded: 'danger', disabled: 'info'
};
const capabilityLabel = computed(() => capabilityLabels[props.capability] || props.capability);
const capabilityType = computed(() => capabilityTypes[props.capability] || 'info');
</script>

<style scoped>
.app-page__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}

.app-page__eyebrow {
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.app-page__heading {
  min-width: 0;
}

.app-page h1 {
  margin: 0;
  color: #172033;
  font-size: 26px;
  letter-spacing: 0;
}

.app-page__heading p {
  margin: 8px 0 0;
  color: #64748b;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.app-page__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.app-page__boundary {
  margin-bottom: 16px;
}

@media (max-width: 720px) {
  .app-page__header {
    flex-direction: column;
    gap: 12px;
  }

  .app-page__heading {
    width: 100%;
  }

  .app-page h1 {
    font-size: 22px;
  }
}
</style>
