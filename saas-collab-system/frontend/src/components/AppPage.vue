<template>
  <section class="app-page">
    <header class="app-page__header">
      <div class="app-page__heading">
        <div v-if="eyebrowLabel" class="app-page__eyebrow">{{ eyebrowLabel }}</div>
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
  mock: '模拟数据', pending: '待接入', sandbox: '沙箱', connected: '已连接', degraded: '降级', disabled: '已禁用'
};
const capabilityTypes = {
  mock: 'warning', pending: 'info', sandbox: 'warning', connected: 'success', degraded: 'danger', disabled: 'info'
};
const capabilityLabel = computed(() => capabilityLabels[props.capability] || props.capability);
const capabilityType = computed(() => capabilityTypes[props.capability] || 'info');
const eyebrowLabels = {
  WORKSPACE: '', 'ROLE WORKSPACE': '工作台', 'MASTER DATA': '基础档案',
  'API DATA INTEGRATION': 'API 数据接入', 'SYSTEM MANAGEMENT': '系统管理',
  'SYSTEM GOVERNANCE': '系统治理', 'SECURITY OPERATIONS': '安全管理',
  'RELEASE GOVERNANCE': '发布治理', 'PRODUCTION GOVERNANCE': '生产治理',
  'PRODUCTION PILOT': '生产试点', 'FEISHU COLLABORATION': '飞书协同',
  'LISTING LOGS': '刊登日志', 'LISTING EXCEPTIONS': '刊登异常',
  'LISTING TASKS': '刊登任务', 'LISTING MAPPINGS': '刊登映射'
};
const eyebrowLabel = computed(() => eyebrowLabels[props.eyebrow] ?? props.eyebrow);
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
  flex-wrap: wrap;
  justify-content: flex-end;
  flex-shrink: 0;
  max-width: 100%;
}

.app-page__actions :deep(.el-button + .el-button) { margin-left: 0; }
.app-page__body { min-width: 0; }

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
  .app-page__actions { justify-content: flex-start; }

  .app-page h1 {
    font-size: 22px;
  }
}
</style>
