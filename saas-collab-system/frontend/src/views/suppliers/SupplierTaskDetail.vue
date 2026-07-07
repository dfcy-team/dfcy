<script setup>
// 后续对接API路径：GET /api/internal/suppliers/tasks/{id}/
const task = {
  task_no: 'ST-20260707001',
  supplier: '华东样品供应商',
  product_code: 'P-20260707001',
  production_quantity: 500,
  completed_quantity: 120,
  expected_ship_date: '2026-07-28',
  status: '生产中',
}

const feedbackRows = [
  { date: '2026-07-07', content: '已确认物料，准备排产', operator: '供应商账号' },
]
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>生产任务信息</h2>
          <el-button type="primary" disabled>采购确认</el-button>
        </div>
      </template>
      <el-form :model="task" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="任务编号">
              <el-input v-model="task.task_no" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="供应商">
              <el-input v-model="task.supplier" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商品编码">
              <el-input v-model="task.product_code" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-input v-model="task.status" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="生产数量">
              <el-input v-model="task.production_quantity" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="已完成数量">
              <el-input v-model="task.completed_quantity" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">供应商回填记录</h2>
      </template>
      <el-table :data="feedbackRows" border>
        <el-table-column prop="date" label="回填日期" min-width="130" />
        <el-table-column prop="content" label="回填内容" min-width="220" />
        <el-table-column prop="operator" label="操作人" min-width="120" />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">异常说明</h2>
      </template>
      <el-input type="textarea" value="暂无异常，后续由供应商端回填。" disabled />
    </el-card>
  </section>
</template>
