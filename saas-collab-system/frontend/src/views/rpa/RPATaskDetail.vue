<script setup>
import { computed } from 'vue'

// 后续对接API路径：GET /api/internal/rpa/tasks/{id}/
// 当前页面仅展示Mock数据，不调用真实 /api/rpa/，不包含任何RPA脚本。
const task = {
  task_no: 'RPA-20260707003',
  task_type: 'BIGSELLER_MULTI_SITE_LISTING',
  business_type: 'listing',
  business_id: 'SITE-002',
  agent: 'agent-win-01',
  status: 'manual_required',
  retry_count: 2,
  created_at: '2026-07-07 10:20',
  finished_at: '-',
  error_reason: 'Mock异常：页面弹窗需要人工确认。',
}

const payload = {
  site_profile_id: 'SITE-002',
  platform: 'BigSeller',
  country: 'US',
  sku: 'SKU-BAG-BLK-S',
}

const result = {
  success: false,
  code: 'MANUAL_REQUIRED',
  message: 'Mock result only. Waiting for manual takeover.',
}

const stepLogs = [
  { time: '2026-07-07 10:20:01', step: 'claim_task', status: 'success', message: 'Agent claimed mock task.' },
  { time: '2026-07-07 10:21:15', step: 'open_bigseller', status: 'success', message: 'Opened mock BigSeller page.' },
  { time: '2026-07-07 10:22:40', step: 'submit_listing', status: 'manual_required', message: 'Mock popup requires manual action.' },
]

const screenshots = [
  { name: '步骤截图-登录后页面', path: 'mock/screenshots/rpa-001-login.png' },
  { name: '步骤截图-弹窗页面', path: 'mock/screenshots/rpa-001-popup.png' },
]

const payloadText = computed(() => JSON.stringify(payload, null, 2))
const resultText = computed(() => JSON.stringify(result, null, 2))
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>任务基础信息</h2>
          <div>
            <el-button type="primary" disabled>重试</el-button>
            <el-button type="warning" disabled>人工接管</el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务编号">{{ task.task_no }}</el-descriptions-item>
        <el-descriptions-item label="任务类型">{{ task.task_type }}</el-descriptions-item>
        <el-descriptions-item label="业务类型">{{ task.business_type }}</el-descriptions-item>
        <el-descriptions-item label="业务ID">{{ task.business_id }}</el-descriptions-item>
        <el-descriptions-item label="Agent">{{ task.agent }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ task.status }}</el-descriptions-item>
        <el-descriptions-item label="重试次数">{{ task.retry_count }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ task.created_at }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ task.finished_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">payload JSON展示</h2>
      </template>
      <pre class="json-block">{{ payloadText }}</pre>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">result JSON展示</h2>
      </template>
      <pre class="json-block">{{ resultText }}</pre>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">步骤日志</h2>
      </template>
      <el-table :data="stepLogs" border>
        <el-table-column prop="time" label="时间" min-width="160" />
        <el-table-column prop="step" label="步骤" min-width="150" />
        <el-table-column prop="status" label="状态" min-width="130" />
        <el-table-column prop="message" label="说明" min-width="260" />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">截图列表</h2>
      </template>
      <el-table :data="screenshots" border>
        <el-table-column prop="name" label="截图名称" min-width="180" />
        <el-table-column prop="path" label="Mock路径" min-width="260" />
        <el-table-column label="操作" width="120">
          <template #default>
            <el-button link type="primary" disabled>预览</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">错误原因</h2>
      </template>
      <el-alert :title="task.error_reason" type="warning" show-icon :closable="false" />
    </el-card>
  </section>
</template>
