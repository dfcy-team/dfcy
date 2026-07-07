<script setup>
// 后续对接API路径：GET /api/internal/purchasing/orders/{id}/
const baseInfo = {
  po_no: 'PO-20260707001',
  supplier: '华东样品供应商',
  delivery_date: '2026-07-30',
  status: '待确认',
  payment_method: '月结30天',
  approval_status: '审批中',
}

const items = [
  { product_code: 'P-20260707001', sku: 'SKU-BAG-BLK-S', name: '便携收纳包', quantity: 500, unit_price: '18.50' },
]
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>采购基础信息</h2>
          <el-button type="primary" disabled>生成供应商生产任务</el-button>
        </div>
      </template>
      <el-form :model="baseInfo" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="采购单号">
              <el-input v-model="baseInfo.po_no" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-input v-model="baseInfo.status" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交期">
              <el-input v-model="baseInfo.delivery_date" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="审批状态">
              <el-input v-model="baseInfo.approval_status" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">商品明细</h2>
      </template>
      <el-table :data="items" border>
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="sku" label="SKU" min-width="150" />
        <el-table-column prop="name" label="商品名称" min-width="160" />
        <el-table-column prop="quantity" label="采购数量" min-width="110" />
        <el-table-column prop="unit_price" label="单价" min-width="100" />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">供应商信息</h2>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="供应商">{{ baseInfo.supplier }}</el-descriptions-item>
        <el-descriptions-item label="付款方式">{{ baseInfo.payment_method }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">审批状态占位</h2>
      </template>
      <el-steps :active="1" finish-status="success">
        <el-step title="提交" />
        <el-step title="审批中" />
        <el-step title="完成" />
      </el-steps>
    </el-card>
  </section>
</template>
