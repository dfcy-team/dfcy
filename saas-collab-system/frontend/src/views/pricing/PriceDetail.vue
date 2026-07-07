<script setup>
// 后续对接API路径：GET /api/internal/pricing/prices/{id}/
const price = {
  product_code: 'P-20260707001',
  sku: 'SKU-BAG-BLK-S',
  purchase_cost: '18.50',
  logistics_cost: '4.20',
  platform_commission: '15%',
  exchange_rate: '7.20',
  target_margin: '28%',
  suggested_price: '29.99',
  approved_price: '28.99',
  clearance_price: '24.99',
}
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>成本构成</h2>
          <el-button type="primary" disabled>提交价格审批</el-button>
        </div>
      </template>
      <el-form :model="price" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="商品编码">
              <el-input v-model="price.product_code" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="SKU">
              <el-input v-model="price.sku" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="采购成本">
              <el-input v-model="price.purchase_cost" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="物流成本">
              <el-input v-model="price.logistics_cost" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="平台佣金">
              <el-input v-model="price.platform_commission" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="汇率">
              <el-input v-model="price.exchange_rate" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">价格测算</h2>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="目标毛利">{{ price.target_margin }}</el-descriptions-item>
        <el-descriptions-item label="建议价格">{{ price.suggested_price }}</el-descriptions-item>
        <el-descriptions-item label="审批价格">{{ price.approved_price }}</el-descriptions-item>
        <el-descriptions-item label="清仓价格占位">{{ price.clearance_price }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </section>
</template>
