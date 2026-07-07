<script setup>
// 后续对接API路径：GET /api/internal/suppliers/shipments/{id}/
const shipment = {
  shipment_no: 'SS-20260707001',
  supplier: '华东样品供应商',
  shipment_quantity: 500,
  cartons: 25,
  weight: '300kg',
  volume: '2.8m³',
  status: '待确认',
}
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>出货基础信息</h2>
          <el-button type="primary" disabled>采购确认</el-button>
        </div>
      </template>
      <el-form :model="shipment" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="出货单号">
              <el-input v-model="shipment.shipment_no" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="供应商">
              <el-input v-model="shipment.supplier" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="出货数量">
              <el-input v-model="shipment.shipment_quantity" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-input v-model="shipment.status" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">箱规信息</h2>
      </template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="箱数">{{ shipment.cartons }}</el-descriptions-item>
        <el-descriptions-item label="重量">{{ shipment.weight }}</el-descriptions-item>
        <el-descriptions-item label="体积">{{ shipment.volume }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">图片/箱唛/物流单附件占位</h2>
      </template>
      <div class="image-placeholders">
        <div>出货图片占位</div>
        <div>箱唛附件占位</div>
        <div>物流单附件占位</div>
      </div>
    </el-card>
  </section>
</template>
