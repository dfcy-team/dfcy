<template>
  <section class="advertising-report-placeholder">
    <header class="page-header">
      <div>
        <p class="eyebrow">{{ module }}</p>
        <h1>{{ plan.title }}</h1>
        <p>{{ plan.description }}</p>
      </div>
      <el-tag type="info" effect="plain">待接入</el-tag>
    </header>

    <el-alert
      title="广告数据尚未接入"
      description="当前仅展示报表规划；查询、导出、真实 BI 与明细穿透将在完成数据校验后开放。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-tabs v-model="activeTab" class="report-tabs">
      <el-tab-pane label="报表规划" name="plan">
        <section class="content-card">
          <h2>计划指标</h2>
          <div class="metric-grid">
            <div v-for="metric in plan.metrics" :key="metric" class="metric-item">
              <span>{{ metric }}</span><strong>— / 未采集</strong>
            </div>
          </div>
          <h2>分析维度</h2>
          <p>{{ plan.dimensions.join('、') }}</p>
          <h2>未来穿透与 BI</h2>
          <p>{{ drilldown }} 接入后可按权限使用字段拖拽、透视、图表及个人或共享 BI 配置；当前不执行真实穿透或 BI 查询。</p>
        </section>
      </el-tab-pane>

      <el-tab-pane label="指标口径" name="definitions">
        <section class="content-card">
          <p>{{ definitionNote }}</p>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="[name, definition] in metricDefinitions" :key="name" :label="name">
              {{ definition }}
            </el-descriptions-item>
          </el-descriptions>
        </section>
      </el-tab-pane>

      <el-tab-pane label="接入条件" name="access">
        <section class="content-card">
          <ul>
            <li v-for="item in plan.access" :key="item">{{ item }}</li>
          </ul>
        </section>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup>
import { ref } from 'vue';

defineProps({
  module: { type: String, required: true },
  plan: { type: Object, required: true },
  drilldown: { type: String, required: true },
  metricDefinitions: { type: Array, required: true },
  definitionNote: { type: String, default: '归因窗口、转化类型、账户时区和币种分开展示；不同口径不直接合并。分母为零或字段缺失时，指标显示不可计算。' }
});

const activeTab = ref('plan');
</script>

<style scoped>
.advertising-report-placeholder { display: grid; gap: 16px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-header h1, .content-card h2 { margin: 0; }
.page-header p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 13px; }
.content-card { padding: 18px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-bg-color); }
.content-card h2 + * { margin-top: 10px; }
.content-card h2:not(:first-child) { margin-top: 24px; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.metric-item { display: flex; justify-content: space-between; gap: 12px; padding: 10px; border-radius: 4px; background: var(--el-fill-color-light); }
.metric-item strong { color: var(--el-text-color-secondary); font-weight: 500; white-space: nowrap; }
.content-card ul { margin: 0; padding-left: 20px; }
.content-card li + li { margin-top: 8px; }
@media (max-width: 640px) { .page-header { flex-direction: column; } .metric-grid { grid-template-columns: 1fr; } }
</style>
