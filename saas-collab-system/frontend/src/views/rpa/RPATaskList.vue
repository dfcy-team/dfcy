<script setup>
// 后续对接API路径：GET /api/internal/rpa/tasks/
// 当前页面仅展示Mock数据，不调用真实 /api/rpa/。
const statuses = [
  'pending',
  'claimed',
  'running',
  'success',
  'failed',
  'retrying',
  'manual_required',
  'cancelled',
]

const taskTypes = [
  'BIGSELLER_CREATE_PRODUCT',
  'BIGSELLER_UPLOAD_IMAGES',
  'BIGSELLER_MULTI_SITE_LISTING',
  'BIGSELLER_UPDATE_PRICE',
  'BIGSELLER_READ_PAGE_PRICE',
  'BIGSELLER_COLLECT_LISTING_STATUS',
]

const rows = [
  {
    task_no: 'RPA-20260707001',
    task_type: 'BIGSELLER_CREATE_PRODUCT',
    business_type: 'listing',
    business_id: 'SITE-001',
    agent: 'agent-win-01',
    status: 'pending',
    retry_count: 0,
    created_at: '2026-07-07 10:00',
    finished_at: '-',
  },
  {
    task_no: 'RPA-20260707002',
    task_type: 'BIGSELLER_UPLOAD_IMAGES',
    business_type: 'product',
    business_id: 'SKU-BAG-BLK-S',
    agent: 'agent-win-02',
    status: 'running',
    retry_count: 1,
    created_at: '2026-07-07 10:10',
    finished_at: '-',
  },
  {
    task_no: 'RPA-20260707003',
    task_type: 'BIGSELLER_MULTI_SITE_LISTING',
    business_type: 'listing',
    business_id: 'SITE-002',
    agent: 'agent-win-01',
    status: 'manual_required',
    retry_count: 2,
    created_at: '2026-07-07 10:20',
    finished_at: '-',
  },
  {
    task_no: 'RPA-20260707004',
    task_type: 'BIGSELLER_UPDATE_PRICE',
    business_type: 'pricing',
    business_id: 'PRICE-001',
    agent: 'agent-win-03',
    status: 'success',
    retry_count: 0,
    created_at: '2026-07-07 10:30',
    finished_at: '2026-07-07 10:35',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="任务类型">
          <el-select placeholder="全部类型" disabled>
            <el-option
              v-for="item in taskTypes"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select placeholder="全部状态" disabled>
            <el-option
              v-for="item in statuses"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" disabled>搜索</el-button>
          <el-button disabled>重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="mvp-table-card" shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>RPA任务中心</h2>
          <el-button type="primary" disabled>创建任务占位</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="task_no" label="任务编号" min-width="170" />
        <el-table-column prop="task_type" label="任务类型" min-width="260" show-overflow-tooltip />
        <el-table-column prop="business_type" label="业务类型" min-width="110" />
        <el-table-column prop="business_id" label="业务ID" min-width="140" />
        <el-table-column prop="agent" label="Agent" min-width="120" />
        <el-table-column prop="status" label="状态" min-width="130" />
        <el-table-column prop="retry_count" label="重试次数" min-width="100" />
        <el-table-column prop="created_at" label="创建时间" min-width="160" />
        <el-table-column prop="finished_at" label="完成时间" min-width="160" />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看详情</el-button>
            <el-button link type="warning" disabled>标记人工接管</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
