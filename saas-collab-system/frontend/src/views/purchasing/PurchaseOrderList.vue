<script setup>
// 后续对接API路径：GET /api/internal/purchasing/orders/
const rows = [
  {
    po_no: 'PO-20260707001',
    product_code: 'P-20260707001',
    sku: 'SKU-BAG-BLK-S',
    supplier: '华东样品供应商',
    quantity: 500,
    unit_price: '18.50',
    delivery_date: '2026-07-30',
    status: '待确认',
    approval_status: '审批中',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="采购单号">
          <el-input placeholder="搜索采购单号" disabled />
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
          <h2>采购订单列表</h2>
          <el-button type="primary" disabled>新增采购单</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="po_no" label="采购单号" min-width="160" />
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="sku" label="SKU" min-width="150" />
        <el-table-column prop="supplier" label="供应商" min-width="150" />
        <el-table-column prop="quantity" label="采购数量" min-width="110" />
        <el-table-column prop="unit_price" label="单价" min-width="100" />
        <el-table-column prop="delivery_date" label="交期" min-width="120" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column prop="approval_status" label="审批状态" min-width="110" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
