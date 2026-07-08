<template>
  <section class="stage0-page">
    <header class="stage0-header">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p class="stage0-note">阶段0页面占位，仅展示 Mock 数据、搜索条件、按钮和字段；不连接真实后端，不执行真实业务提交。</p>
      </div>
      <el-tag type="info">API: {{ apiPath }}</el-tag>
    </header>

    <el-form class="stage0-search" inline>
      <el-form-item v-for="item in searchFields" :key="item" :label="item">
        <el-input placeholder="Mock 搜索条件" disabled />
      </el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <div class="stage0-actions">
      <el-button v-for="action in actions" :key="action" disabled>{{ action }}</el-button>
    </div>

    <div class="placeholder-grid">
      <div v-for="field in fields" :key="field" class="placeholder-card">
        <span class="field-label">{{ field }}</span>
        <span class="field-value">Mock 字段占位</span>
      </div>
    </div>

    <div v-if="extraItems.length" class="stage0-extra">
      <span v-for="item in extraItems" :key="item">{{ item }}</span>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  title: { type: String, required: true },
  apiPath: { type: String, default: 'pending' },
  fields: { type: Array, default: () => [] },
  searchFields: { type: Array, default: () => ['编号', '状态'] },
  actions: { type: Array, default: () => ['新增占位', '导出占位'] },
  extraItems: { type: Array, default: () => [] }
});

const { title, apiPath, fields, searchFields, actions, extraItems } = props;
</script>

<style scoped>
.stage0-page {
  display: grid;
  gap: 16px;
}

.stage0-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.stage0-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.stage0-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.stage0-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage0-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage0-extra span {
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  font-size: 12px;
}
</style>
