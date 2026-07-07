<script setup>
// 后续对接API路径：GET /api/internal/suppliers/tasks/
const rows = [
  {
    task_no: 'ST-20260707001',
    supplier: '华东样品供应商',
    product_code: 'P-20260707001',
    production_quantity: 500,
    completed_quantity: 120,
    expected_ship_date: '2026-07-28',
    status: '生产中',
    overdue: '否',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="任务编号">
          <el-input placeholder="搜索任务编号" disabled />
        </el-form-item>
        <el-form-item label="状态">
          <el-select placeholder="全部状态" disabled>
            <el-option label="生产中" value="production" />
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
          <h2>供应商任务列表</h2>
          <el-button type="primary" disabled>同步任务</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="task_no" label="任务编号" min-width="160" />
        <el-table-column prop="supplier" label="供应商" min-width="150" />
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="production_quantity" label="生产数量" min-width="110" />
        <el-table-column prop="completed_quantity" label="已完成数量" min-width="120" />
        <el-table-column prop="expected_ship_date" label="预计出货日期" min-width="130" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column prop="overdue" label="是否逾期" min-width="100" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
