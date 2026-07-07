<script setup>
// 后续对接API路径：GET /api/internal/integrations/sync-logs/
// 当前页面仅展示Mock数据，不接真实API。
const rows = [
  {
    log_no: 'SYNCLOG-20260707001',
    platform: 'BigSeller',
    sync_type: '商品资料同步',
    status: 'success',
    started_at: '2026-07-07 09:00',
    ended_at: '2026-07-07 09:03',
    error_message: '-',
    quality_check_result: '通过',
  },
  {
    log_no: 'SYNCLOG-20260707002',
    platform: 'Amazon',
    sync_type: '价格同步',
    status: 'failed',
    started_at: '2026-07-07 09:20',
    ended_at: '2026-07-07 09:21',
    error_message: 'Mock错误：远程字段缺失',
    quality_check_result: '待复核',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="日志编号">
          <el-input placeholder="搜索日志编号" disabled />
        </el-form-item>
        <el-form-item label="状态">
          <el-select placeholder="全部状态" disabled>
            <el-option label="success" value="success" />
            <el-option label="failed" value="failed" />
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
          <h2>API同步日志列表</h2>
          <el-button type="primary" disabled>导出日志</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="log_no" label="日志编号" min-width="180" />
        <el-table-column prop="platform" label="平台" min-width="110" />
        <el-table-column prop="sync_type" label="同步类型" min-width="150" />
        <el-table-column prop="status" label="状态" min-width="110" />
        <el-table-column prop="started_at" label="开始时间" min-width="160" />
        <el-table-column prop="ended_at" label="结束时间" min-width="160" />
        <el-table-column prop="error_message" label="错误信息" min-width="220" show-overflow-tooltip />
        <el-table-column prop="quality_check_result" label="数据质量检查结果" min-width="160" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
