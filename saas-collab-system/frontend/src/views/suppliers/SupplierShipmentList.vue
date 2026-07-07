<script setup>
// 后续对接API路径：GET /api/internal/suppliers/shipments/
const rows = [
  {
    shipment_no: 'SS-20260707001',
    supplier: '华东样品供应商',
    shipment_quantity: 500,
    cartons: 25,
    weight: '300kg',
    volume: '2.8m³',
    status: '待确认',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="出货单号">
          <el-input placeholder="搜索出货单号" disabled />
        </el-form-item>
        <el-form-item label="供应商">
          <el-input placeholder="搜索供应商" disabled />
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
          <h2>供应商发货列表</h2>
          <el-button type="primary" disabled>创建出货单</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="shipment_no" label="出货单号" min-width="160" />
        <el-table-column prop="supplier" label="供应商" min-width="150" />
        <el-table-column prop="shipment_quantity" label="出货数量" min-width="110" />
        <el-table-column prop="cartons" label="箱数" min-width="90" />
        <el-table-column prop="weight" label="重量" min-width="100" />
        <el-table-column prop="volume" label="体积" min-width="100" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
