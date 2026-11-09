<template>
  <section v-if="rows.length" aria-label="达人和视频采集进度">
    <h2>达人 / 视频采集进度</h2>
    <el-alert type="info" :closable="false" title="仅查看已入库证据，不开启能力或定时任务。调度状态未接入，不能根据有数据判断定时器正在运行。" />
    <el-table :data="rows" border>
      <el-table-column prop="label" label="采集能力" width="140" />
      <el-table-column label="状态" min-width="180"><template #default="{ row }">{{ row.visibility === 'restricted' ? '无执行记录查看权限' : statusLabel(row.latest_status) }}</template></el-table-column>
      <el-table-column label="最近记录时间" min-width="220"><template #default="{ row }">{{ row.last_at || '暂无记录' }}</template></el-table-column>
      <el-table-column label="入库证据" min-width="270"><template #default="{ row }">
        <template v-if="row.visibility !== 'restricted' && row.code === 'CREATOR'">{{ row.stored_count ?? '未知' }} 条快照；{{ row.verified_count ?? '未知' }} 条身份匹配</template>
        <template v-else-if="row.visibility !== 'restricted'">最近批次 {{ row.stored_count ?? '未确认' }} 条视频日记录</template>
        <span v-else>不可查看</span>
      </template></el-table-column>
      <el-table-column label="自动调度" min-width="150"><template #default>未核实，不自动启用</template></el-table-column>
    </el-table>
    <template v-for="row in rows" :key="row.code">
      <template v-if="row.code === 'VIDEO' && row.visibility !== 'restricted'">
        <h3>视频最近14个批次</h3>
        <el-table :data="row.recent_batches || []" border empty-text="暂无采集批次，不代表店铺没有视频">
          <el-table-column prop="id" label="批次ID" />
          <el-table-column prop="window_start" label="开始日期" />
          <el-table-column prop="window_end" label="结束日期（不含）" />
          <el-table-column label="状态"><template #default="{ row: batch }">{{ statusLabel(batch.status) }}</template></el-table-column>
          <el-table-column label="视频日记录"><template #default="{ row: batch }">{{ batch.status === 'completed' ? batch.video_count : '未确认' }}</template></el-table-column>
          <el-table-column prop="detail_succeeded_count" label="详情成功" />
          <el-table-column prop="detail_failed_count" label="详情失败" />
          <el-table-column prop="next_retry_at" label="批次下次重试时间" min-width="200" />
        </el-table>
      </template>
    </template>
  </section>
</template>

<script setup>
defineProps({ rows: { type: Array, default: () => [] } });
const statusLabel = (value) => ({ completed: '批次已完成', running: '运行中（记录状态）', pending: '待执行', failed: '失败，需核查批次', cancelled: '已取消', has_snapshots: '已有快照，不代表全部核验通过', no_records: '暂无记录' }[value] || '未知');
</script>
