<script setup>
// 后续对接API路径：GET /api/internal/integrations/sync-tasks/
// 当前页面仅展示Mock数据，不接真实API。
const rows = [
  {
    task_no: 'SYNC-20260707001',
    platform: 'BigSeller',
    store: 'Mock Store US',
    sync_type: '商品资料同步',
    status: 'pending',
    last_sync_at: '2026-07-07 09:00',
    next_sync_at: '2026-07-07 11:00',
    retry_count: 0,
  },
  {
    task_no: 'SYNC-20260707002',
    platform: 'Amazon',
    store: 'Mock Store DE',
    sync_type: '价格同步',
    status: 'running',
    last_sync_at: '2026-07-07 08:30',
    next_sync_at: '2026-07-07 10:30',
    retry_count: 1,
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="平台">
          <el-select placeholder="全部平台" disabled>
            <el-option label="BigSeller" value="BigSeller" />
            <el-option label="Amazon" value="Amazon" />
          </el-select>
        </el-form-item>
        <el-form-item label="同步类型">
          <el-input placeholder="搜索同步类型" disabled />
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
          <h2>API同步任务列表</h2>
          <el-button type="primary" disabled>新增同步任务</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="task_no" label="任务编号" min-width="170" />
        <el-table-column prop="platform" label="平台" min-width="110" />
        <el-table-column prop="store" label="店铺" min-width="150" />
        <el-table-column prop="sync_type" label="同步类型" min-width="150" />
        <el-table-column prop="status" label="状态" min-width="110" />
        <el-table-column prop="last_sync_at" label="上次同步时间" min-width="160" />
        <el-table-column prop="next_sync_at" label="下次同步时间" min-width="160" />
        <el-table-column prop="retry_count" label="重试次数" min-width="100" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
